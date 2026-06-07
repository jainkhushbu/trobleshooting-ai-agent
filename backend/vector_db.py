# backend/vector_db.py
import re
import math
import uuid
import hashlib
import requests
from collections import Counter
import chromadb
from chromadb.api.types import EmbeddingFunction, Documents, Embeddings

def get_gemini_embeddings(texts, api_key):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:batchEmbedContents?key={api_key}"
    headers = {"Content-Type": "application/json"}
    
    requests_list = []
    for t in texts:
        requests_list.append({
            "model": "models/text-embedding-004",
            "content": {
                "parts": [{"text": t}]
            }
        })
    payload = {"requests": requests_list}
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        if response.status_code == 200:
            res_data = response.json()
            embeddings = []
            for emb_data in res_data.get("embeddings", []):
                embeddings.append(emb_data["values"])
            return embeddings
    except Exception as e:
        print(f"Error calling Gemini Embeddings: {e}")
    return None

def get_hash_embeddings(texts):
    embeddings = []
    for text in texts:
        vector = [0.0] * 768
        tokens = [w.lower() for w in re.findall(r'[a-zA-Z]{3,}', text)]
        if not tokens:
            embeddings.append(vector)
            continue
        for token in tokens:
            digest = hashlib.md5(token.encode('utf-8')).hexdigest()
            h = int(digest, 16) % 768
            vector[h] += 1.0
        norm = math.sqrt(sum(x**2 for x in vector))
        if norm > 0:
            vector = [x / norm for x in vector]
        embeddings.append(vector)
    return embeddings

class GeminiEmbeddingFunction(EmbeddingFunction):
    def __init__(self, api_key=None):
        self.api_key = api_key

    def __call__(self, input: Documents) -> Embeddings:
        if self.api_key:
            embeddings = get_gemini_embeddings(input, self.api_key)
            if embeddings:
                return embeddings
        return get_hash_embeddings(input)

class RuntimeVectorDB:
    """
    A runtime Vector Database using ChromaDB under the hood, with
    sliding window chunking, Gemini Embeddings API, and local hashing fallback.
    """
    def __init__(self, api_key=None):
        self.api_key = api_key
        self.client = chromadb.Client()
        self.collection_name = f"troubleshoot_col_{uuid.uuid4().hex}"
        self.embedding_fn = GeminiEmbeddingFunction(api_key=self.api_key)
        self.collection = self.client.create_collection(
            name=self.collection_name,
            embedding_function=self.embedding_fn
        )

    def _tokenize(self, text):
        return [w.lower() for w in re.findall(r'[a-zA-Z]{3,}', text)]

    def add_document(self, text, metadata):
        """Chunks document text using sliding window and registers in Chroma collection."""
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        doc_name = metadata.get("document_name", "unknown")
        
        # Sliding window chunking (window_size=6, overlap=3)
        window_size = 6
        overlap = 3
        
        chunks = []
        if len(lines) <= window_size:
            chunks.append("\n".join(lines))
        else:
            step = window_size - overlap
            for i in range(0, len(lines) - window_size + 1, step):
                chunks.append("\n".join(lines[i:i+window_size]))
                
        documents = []
        metadatas = []
        ids = []
        
        for idx, chunk in enumerate(chunks):
            if not chunk.strip():
                continue
                
            doc_id = f"{doc_name}-SW-{idx}-{uuid.uuid4().hex[:6]}"
            
            start_line = idx * (window_size - overlap) + 1
            end_line = start_line + len(chunk.splitlines()) - 1
            
            documents.append(chunk)
            metadatas.append({
                "document_name": doc_name,
                "chunk_index": idx,
                "title": f"Lines {start_line}-{end_line} in {doc_name}",
                "match_trigger": chunk.splitlines()[0][:50] if chunk.splitlines() else doc_name
            })
            ids.append(doc_id)
            
        if documents:
            self.collection.add(
                documents=documents,
                metadatas=metadatas,
                ids=ids
            )

    def search(self, query, top_n=10):
        """
        Runs query matching in Chroma DB collection.
        Returns a list of matching chunks with similarity scores.
        """
        if self.collection.count() == 0:
            return []
            
        results = self.collection.query(
            query_texts=[query],
            n_results=min(top_n, self.collection.count())
        )
        
        if not results or not results['ids'] or not results['ids'][0]:
            return []
            
        formatted_results = []
        ids = results['ids'][0]
        documents = results['documents'][0]
        metadatas = results['metadatas'][0]
        
        distances = results['distances'][0] if 'distances' in results and results['distances'] else [0.2] * len(ids)
        
        for idx in range(len(ids)):
            dist = distances[idx]
            sim = 1.0 - max(0.0, min(1.0, dist))
            
            query_clean = query.lower()
            text_clean = documents[idx].lower()
            overlap_bonus = self._get_overlap_bonus(query_clean, text_clean)
            
            total_score = sim * 0.7 + overlap_bonus * 0.3
            confidence = int(total_score * 100)
            if confidence > 99:
                confidence = 99
            if confidence < 10:
                confidence = 35
                
            formatted_results.append({
                "id": ids[idx],
                "title": metadatas[idx]["title"],
                "match_trigger": metadatas[idx]["match_trigger"],
                "summary": documents[idx][:150] + "...",
                "cause": f"System matched query pattern in {metadatas[idx]['document_name']}.",
                "resolution": documents[idx],
                "commands": self._generate_simulated_commands(documents[idx]),
                "document_name": metadatas[idx]["document_name"],
                "confidence": f"{confidence}%"
            })
            
        formatted_results.sort(key=lambda x: int(x["confidence"].replace("%", "")), reverse=True)
        return formatted_results[:top_n]

    def _get_overlap_bonus(self, query, text):
        """Computes overlap ratio as a supporting score booster."""
        q_lines = [l.strip() for l in query.splitlines() if l.strip()]
        t_lines = [l.strip() for l in text.splitlines() if l.strip()]
        
        max_overlap = 0.0
        for q_line in q_lines:
            q_clean = re.sub(r'\d{4}[-/]\d{2}[-/]\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?', '', q_line)
            q_clean = re.sub(r'\[\w+\]|\d+#\d+: \*\d+', '', q_clean)
            q_tokens = set(self._tokenize(q_clean))
            if len(q_tokens) < 2:
                continue
                
            for t_line in t_lines:
                t_tokens = set(self._tokenize(t_line))
                if len(t_tokens) < 2:
                    continue
                intersection = q_tokens.intersection(t_tokens)
                if intersection:
                    ratio = len(intersection) / min(len(q_tokens), len(t_tokens))
                    if ratio > max_overlap:
                        max_overlap = ratio
        return max_overlap

    def _generate_simulated_commands(self, text):
        """Generates standard verification/recovery commands based on match content keywords."""
        text_lower = text.lower()
        if "nginx" in text_lower:
            return [
                "nginx -t",
                "cat /etc/nginx/nginx.conf | grep client_body_buffer_size",
                "sudo systemctl reload nginx"
            ]
        elif "ssh" in text_lower or "sshd" in text_lower or "authorized_keys" in text_lower:
            return [
                "ls -la ~/.ssh",
                "chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys",
                "sudo systemctl restart sshd"
            ]
        elif "oom" in text_lower or "memory" in text_lower or "oomkilled" in text_lower:
            return [
                "kubectl get pods -n default",
                "kubectl describe pod -n default",
                "kubectl top nodes"
            ]
        elif "postgres" in text_lower or "sql" in text_lower or "db" in text_lower or "timeout" in text_lower:
            return [
                "psql -U postgres -c 'SHOW max_connections;'",
                "psql -U postgres -c 'SELECT count(*) FROM pg_stat_activity;'",
                "sudo systemctl restart postgresql"
            ]
        return ["echo 'Perform manual system diagnostics'", "uptime", "free -m"]
