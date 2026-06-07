# backend/search.py
import os
import re
import json
import requests
from backend.vector_db import RuntimeVectorDB

def call_gemini_match(log_text, sections, api_key):
    """Semantic matching using Gemini 1.5 Flash."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    
    candidates = []
    for sec in sections:
        candidates.append({
            "id": sec["id"],
            "title": sec["title"],
            "match_trigger": sec["match_trigger"],
            "summary": sec["summary"]
        })
        
    prompt = f"""You are a systems troubleshooter. Analyze the following system log query and evaluate the candidate troubleshooting steps.
Log Query:
{log_text[:2500]}

Candidates:
{json.dumps(candidates, indent=2)}

Evaluate the relevance of each candidate. Return a JSON list of matches, each containing "id" (string matching the candidate's id), "confidence" (integer 0-100 representing confidence score), and "reason" (string, short explanation of why it matches or why it does not match).
Example output:
[
  {{"id": "TS-102", "confidence": 95, "reason": "Log indicates client intended to send too large body which matches Nginx buffer overflow."}}
]
Only return the raw JSON list, no markdown blocks, no explanation.
"""

    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "responseMimeType": "application/json"
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=12)
        if response.status_code == 200:
            res_data = response.json()
            text_response = res_data["contents"][0]["parts"][0]["text"].strip()
            if text_response.startswith("```"):
                text_response = re.sub(r'^```json\s*|^```\s*|```$', '', text_response, flags=re.MULTILINE).strip()
            matches = json.loads(text_response)
            return {m["id"]: (int(m["confidence"]), m.get("reason", "")) for m in matches if "id" in m}
    except Exception as e:
        print(f"Gemini API Error: {e}")
    return {}

import zipfile
import xml.etree.ElementTree as ET

def extract_text_from_docx(docx_file):
    """Extracts text from a binary .docx file-like object using standard library."""
    try:
        with zipfile.ZipFile(docx_file) as z:
            xml_content = z.read('word/document.xml')
            root = ET.fromstring(xml_content)
            namespaces = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            paragraphs = root.findall('.//w:p', namespaces)
            text_runs = []
            for paragraph in paragraphs:
                texts = paragraph.findall('.//w:t', namespaces)
                p_text = "".join([t.text for t in texts if t.text])
                if p_text.strip():
                    text_runs.append(p_text)
            return "\n".join(text_runs)
    except Exception as e:
        print(f"Error parsing docx: {e}")
        return ""

def search_documents(query, uploaded_files=None, local_steps_path="local_steps.txt", api_key=None, force_local=False):
    """
    Core search engine. Indexes files in RuntimeVectorDB and returns similarity matches.
    """
    # 1. Initialize Vector Database with API key for Chroma embedding function
    vdb = RuntimeVectorDB(api_key=api_key)
    
    # 2. Load uploaded files
    sources_loaded = False
    if uploaded_files:
        for f in uploaded_files:
            try:
                f.seek(0)
                if f.name.lower().endswith(".docx"):
                    text = extract_text_from_docx(f)
                else:
                    content = f.read()
                    text = content.decode("utf-8", errors="ignore")
                f.seek(0)
                if text.strip():
                    vdb.add_document(text, {"document_name": f.name})
                    sources_loaded = True
            except Exception as e:
                print(f"Error loading uploaded file {f.name}: {e}")
                
    # 3. Load local steps file ONLY if force_local is True or no uploaded files were successfully loaded
    if (force_local or not sources_loaded) and local_steps_path and os.path.exists(local_steps_path):
        try:
            with open(local_steps_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                if content.strip():
                    vdb.add_document(content, {"document_name": local_steps_path})
                    sources_loaded = True
        except Exception as e:
            print(f"Error loading local steps: {e}")
            
    # Fallback to embedded documentation if no sources are successfully indexed
    if not sources_loaded:
        from app import MOCK_TS_STEPS
        fallback_text = ""
        for ts in MOCK_TS_STEPS:
            fallback_text += f"=== DOCUMENT: {ts['title']} ({ts['id']}) ===\n"
            fallback_text += f"Trigger: {ts['match_trigger']}\n"
            fallback_text += f"Summary: {ts['summary']}\n"
            fallback_text += f"Cause: {ts['cause']}\n"
            fallback_text += f"Resolution: {ts['resolution']}\n"
            fallback_text += f"Commands:\n" + "\n".join(ts['commands']) + "\n\n"
        vdb.add_document(fallback_text, {"document_name": "Embedded Knowledge Base"})


    # 4. Search the vector database using query
    results = vdb.search(query, top_n=12)
    if not results:
        return []
        
    # 5. If Gemini API Key is provided, perform deep semantic ranker pass
    gemini_scores = {}
    if api_key:
        gemini_scores = call_gemini_match(query, results, api_key)
        
    scored_results = []
    for sec in results:
        if sec["id"] in gemini_scores:
            conf, reason = gemini_scores[sec["id"]]
            if conf > 0:
                sec_copy = sec.copy()
                sec_copy["confidence"] = f"{conf}%"
                if reason:
                    sec_copy["cause"] = f"**LLM Match Reason**: {reason}\n\n{sec['cause']}"
                if conf >= 80:
                    sec_copy["class"] = "conf-high"
                elif conf >= 50:
                    sec_copy["class"] = "conf-med"
                else:
                    sec_copy["class"] = "conf-low"
                scored_results.append((conf, sec_copy))
        else:
            # Fall back to RuntimeVectorDB similarity score
            conf = int(sec["confidence"].replace("%", ""))
            sec_copy = sec.copy()
            if conf >= 80:
                sec_copy["class"] = "conf-high"
            elif conf >= 50:
                sec_copy["class"] = "conf-med"
            else:
                sec_copy["class"] = "conf-low"
            scored_results.append((conf, sec_copy))
            
    scored_results.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in scored_results]
