# app.py
import streamlit as st
import time
import os

# Set page config for a widescreen layout and dark theme base
st.set_page_config(
    page_title="AI Troubleshooting Agent",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Load fontawesome icons
st.markdown('<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">', unsafe_allow_html=True)

# Load CSS stylesheet
if os.path.exists("styles.css"):
    with open("styles.css", "r") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# Define mock troubleshooting database
MOCK_TS_STEPS = [
    {
        "id": "TS-102",
        "title": "TS-102: Nginx Buffer Overflow Error",
        "confidence": "94%",
        "class": "conf-high",
        "match_trigger": "client intended to send too large body",
        "summary": "Nginx client request body buffer size is smaller than the incoming payload, causing the server to reject the requests.",
        "cause": "Incoming payload size (approx 18MB - 24MB) exceeds the configured `client_body_buffer_size` and `client_max_body_size` in nginx.conf.",
        "resolution": "Increase buffer limits. Update `/etc/nginx/nginx.conf` and set:\n`client_max_body_size 50M;`\n`client_body_buffer_size 128k;`\nThen run `nginx -s reload`.",
        "commands": [
            "sudo nginx -t",
            "cat /etc/nginx/nginx.conf | grep client_body_buffer_size",
            "sudo sed -i 's/http {/http {\\n    client_max_body_size 50M;\\n    client_body_buffer_size 128k;/g' /etc/nginx/nginx.conf",
            "sudo systemctl reload nginx",
            "nginx -t"
        ]
    },
    {
        "id": "TS-205",
        "title": "TS-205: SSH Authentication Failure",
        "confidence": "87%",
        "class": "conf-high",
        "match_trigger": "sshd",
        "summary": "SSH daemon rejected login attempts for user due to invalid permissions on key directory or invalid authentication keys.",
        "cause": "Permissions on the user's `~/.ssh` directory or `~/.ssh/authorized_keys` are too open, prompting the sshd daemon to ignore the keys.",
        "resolution": "Secure the directory permissions:\nRun `chmod 700 ~/.ssh` and `chmod 600 ~/.ssh/authorized_keys` to ensure proper ownership and lock down access rights.",
        "commands": [
            "ls -la ~/.ssh",
            "chmod 700 ~/.ssh",
            "chmod 600 ~/.ssh/authorized_keys",
            "sudo systemctl restart sshd"
        ]
    },
    {
        "id": "TS-309",
        "title": "TS-309: Kubernetes OOMKilled Pod",
        "confidence": "76%",
        "class": "conf-med",
        "match_trigger": "OOMKilled",
        "summary": "Container in the pod has reached its designated memory limits and was terminated by the Linux Out-Of-Memory killer.",
        "cause": "The application process inside container `cognitive-agent-core` requested more RAM than allocated in the deployment manifests specifications.",
        "resolution": "Increase resource memory limits in the YAML deployment spec:\nSet `resources.limits.memory` to `1Gi` or higher to allow headroom for spiking jobs.",
        "commands": [
            "kubectl get pod",
            "kubectl describe pod -n default",
            "kubectl patch deployment cognitive-agent -p '{\"spec\":{\"template\":{\"spec\":{\"containers\":[{\"name\":\"cognitive-agent-core\",\"resources\":{\"limits\":{\"memory\":\"1Gi\"}}}]}}}}'"
        ]
    },
    {
        "id": "TS-412",
        "title": "TS-412: Database Connection Timeout",
        "confidence": "61%",
        "class": "conf-med",
        "match_trigger": "connection limit exceeded",
        "summary": "Database server is refusing connection requests because the maximum connection threshold has been reached.",
        "cause": "Max connection pool limits on PostgreSQL are saturated due to lingering connections and un-closed client cursors.",
        "resolution": "Raise maximum client connections in `postgresql.conf` to `250` and implement aggressive connection pool timeout limits.",
        "commands": [
            "psql -U postgres -c 'SHOW max_connections;'",
            "psql -U postgres -c \"SELECT count(*), state FROM pg_stat_activity GROUP BY state;\"",
            "sudo sed -i 's/max_connections = 100/max_connections = 250/g' /var/lib/pgsql/data/postgresql.conf",
            "sudo systemctl restart postgresql"
        ]
    }
]

# Initialize Session State
if "page" not in st.session_state:
    st.session_state.page = "input"
if "log_text" not in st.session_state:
    st.session_state.log_text = ""
if "log_text_area" not in st.session_state:
    st.session_state.log_text_area = ""
if "search_triggered" not in st.session_state:
    st.session_state.search_triggered = False
if "selected_ts_idx" not in st.session_state:
    st.session_state.selected_ts_idx = 0
if "ssh_connected" not in st.session_state:
    st.session_state.ssh_connected = False
if "ssh_connecting" not in st.session_state:
    st.session_state.ssh_connecting = False
if "ssh_host" not in st.session_state:
    st.session_state.ssh_host = ""
if "ssh_username" not in st.session_state:
    st.session_state.ssh_username = ""
if "refinement" not in st.session_state:
    st.session_state.refinement = ""
if "current_menu" not in st.session_state:
    st.session_state.current_menu = "Troubleshooting"
if "uploaded_docs_list" not in st.session_state:
    st.session_state.uploaded_docs_list = []
if "search_results" not in st.session_state:
    st.session_state.search_results = []
if "match_approved" not in st.session_state:
    st.session_state.match_approved = False
if "resolution_approved" not in st.session_state:
    st.session_state.resolution_approved = False
if "execution_completed" not in st.session_state:
    st.session_state.execution_completed = False
if "generated_bash_script" not in st.session_state:
    st.session_state.generated_bash_script = ""
if "script_approved" not in st.session_state:
    st.session_state.script_approved = False
if "show_approve_modal" not in st.session_state:
    st.session_state.show_approve_modal = False
if "execution_started" not in st.session_state:
    st.session_state.execution_started = False
if "console_logs" not in st.session_state:
    st.session_state.console_logs = []
if "gemini_api_key" not in st.session_state:
    st.session_state.gemini_api_key = "AQ.Ab8RN6KSSOYFlvreu6RWVQ6U5po0zErPs90vEzUT2iGxyoQeDQ"

# Delegate Search to Backend module (with auto-reload to ensure changes apply immediately)
import importlib
import backend.search
importlib.reload(backend.search)
from backend.search import search_documents

def execute_search(query, uploaded_files=None):
    # Fetch from session state or environment first, fall back to user's secret key backend-only
    api_key = st.session_state.get("gemini_api_key")
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY", os.environ.get("GOOGLE_API_KEY", ""))
    if not api_key:
        api_key = "AQ.Ab8RN6KSSOYFlvreu6RWVQ6U5po0zErPs90vEzUT2iGxyoQeDQ"
    force_local = st.session_state.get("use_existing", False)
    return search_documents(query, uploaded_files, api_key=api_key, force_local=force_local)

def edit_bash_script_with_gemini(script, feedback, api_key):
    """Regenerates/refines the bash script based on user feedback using Gemini."""
    import requests
    import re
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    
    prompt = f"""You are a systems troubleshooter and bash scripting expert.
Edit the following bash script based on the user's feedback.

Current Bash Script:
```bash
{script}
```

User Feedback/Request:
"{feedback}"

Return ONLY the updated bash script. Do not include markdown blocks, do not include backticks, do not write explanations. Start directly with #!/bin/bash.
"""
    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }]
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=12)
        if response.status_code == 200:
            res_data = response.json()
            text_response = res_data["contents"][0]["parts"][0]["text"].strip()
            if text_response.startswith("```"):
                text_response = re.sub(r'^```bash\s*|^```\s*|```$', '', text_response, flags=re.MULTILINE).strip()
            return text_response
    except Exception as e:
        print(f"Error editing script: {e}")
    return script + f"\n\n# Updated with feedback: {feedback}\n"

# Helper functions
def reset_approval_states():
    st.session_state.match_approved = False
    st.session_state.resolution_approved = False
    st.session_state.execution_completed = False
    st.session_state.generated_bash_script = ""
    st.session_state.script_approved = False
    st.session_state.show_approve_modal = False
    st.session_state.execution_started = False
    st.session_state.console_logs = []

def initialize_execution_state(selected_ts):
    # Generate default bash script text
    bash_script_lines = [
        "#!/bin/bash",
        f"# Resolution script for {selected_ts.get('title', 'Troubleshooting Match')}",
        f"# Target Environment: {st.session_state.ssh_host if st.session_state.ssh_host else 'Local Sandbox'}",
        f"# Generated by AI Troubleshooting Agent",
        "",
        "echo 'Starting resolution script execution...'",
    ]
    for cmd in selected_ts.get("commands", []):
        bash_script_lines.append(f"echo 'Running: {cmd}'")
        bash_script_lines.append(cmd)
        bash_script_lines.append("if [ $? -ne 0 ]; then")
        bash_script_lines.append("  echo 'Error: command failed. Exiting.'")
        bash_script_lines.append("  exit 1")
        bash_script_lines.append("fi")
    bash_script_lines.append("")
    bash_script_lines.append("echo 'Resolution completed successfully.'")
    
    st.session_state.generated_bash_script = "\n".join(bash_script_lines)
    st.session_state.script_approved = False
    st.session_state.show_approve_modal = False
    st.session_state.execution_started = False
    st.session_state.execution_completed = False
    st.session_state.console_logs = []

def handle_feedback():
    fb = st.session_state.script_feedback_input
    if fb:
        api_key = st.session_state.get("gemini_api_key", "")
        updated_script = edit_bash_script_with_gemini(st.session_state.generated_bash_script, fb, api_key)
        st.session_state.generated_bash_script = updated_script
        st.session_state.script_approved = False
        st.session_state.show_approve_modal = False
        st.session_state.execution_started = False
        st.session_state.execution_completed = False
        st.session_state.console_logs = []
        st.session_state.script_feedback_input = ""

def set_log_text(text):
    st.session_state.log_text = text
    st.session_state.log_text_area = text
    st.session_state.search_triggered = False
    st.session_state.search_results = []
    reset_approval_states()

def clear_logs():
    st.session_state.log_text = ""
    st.session_state.log_text_area = ""
    st.session_state.search_triggered = False
    st.session_state.search_results = []
    reset_approval_states()

def trigger_search(uploaded_files=None):
    if st.session_state.log_text.strip():
        st.session_state.search_results = execute_search(st.session_state.log_text, uploaded_files)
        st.session_state.search_triggered = True
        st.session_state.selected_ts_idx = 0
        reset_approval_states()
    else:
        st.session_state.search_triggered = False
        st.session_state.search_results = []
        reset_approval_states()

def extract_timestamped_logs(user_log, match_trigger):
    """
    Scans user log to extract lines matching the signature, including timestamps.
    """
    import re
    matched_lines = []
    lines = user_log.splitlines()
    for line in lines:
        if not line.strip():
            continue
        trigger_words = [w.lower() for w in re.findall(r'\w+', match_trigger) if len(w) > 3]
        has_overlap = any(w in line.lower() for w in trigger_words)
        
        if has_overlap:
            timestamp = "Detected at Runtime"
            ts_match = re.search(r'\d{4}[-/]\d{2}[-/]\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?', line)
            if ts_match:
                timestamp = ts_match.group(0)
            else:
                ts_match = re.search(r'^\w{3} \s?\d{1,2} \d{2}:\d{2}:\d{2}', line)
                if ts_match:
                    timestamp = ts_match.group(0)
            
            clean_msg = line
            if ts_match:
                clean_msg = clean_msg.replace(ts_match.group(0), "").strip()
            if len(clean_msg) > 120:
                clean_msg = clean_msg[:120] + "..."
                
            matched_lines.append({
                "timestamp": timestamp,
                "message": clean_msg
            })
            
    if not matched_lines:
        for line in lines:
            if line.strip():
                matched_lines.append({
                    "timestamp": "Detected at Runtime",
                    "message": line.strip()[:100] + "..." if len(line.strip()) > 100 else line.strip()
                })
                break
                
    return matched_lines

# --- SIDEBAR RENDERING ---
with st.sidebar:
    # Custom Brand Logo
    st.markdown("""
    <div class="brand-container">
        <div class="brand-title">Cognitive Debugger</div>
        <div class="brand-version">v2.4.0-stable</div>
    </div>
    """, unsafe_allow_html=True)
    
    # New Session Button
    if st.button("+ New Session", key="btn_new", type="primary"):
        st.session_state.page = "input"
        st.session_state.log_text = ""
        st.session_state.search_triggered = False
        st.session_state.selected_ts_idx = 0
        st.session_state.ssh_connected = False
        st.session_state.uploaded_docs_list = []
        st.session_state.refinement = ""
        st.session_state.search_results = []
        reset_approval_states()
        st.rerun()
        
    # Navigation Menu Items (Styled like list links)
    menus = [
        {"name": "Troubleshooting", "icon": "fa-solid fa-screwdriver-wrench"},
        {"name": "History", "icon": "fa-solid fa-clock-rotate-left"},
        {"name": "Knowledge Base", "icon": "fa-solid fa-book-open-reader"},
        {"name": "Execution", "icon": "fa-solid fa-circle-play"},
        {"name": "Reports", "icon": "fa-solid fa-chart-simple"}
    ]
    
    st.markdown('<div class="menu-list">', unsafe_allow_html=True)
    for m in menus:
        is_active = st.session_state.current_menu == m["name"]
        active_class = "active" if is_active else ""
        # Renders beautiful layout via raw markdown injection and standard button overlays
        btn_label = f"{m['name']}"
        if st.button(f" {btn_label}", key=f"menu_{m['name']}", use_container_width=True):
            st.session_state.current_menu = m["name"]
            st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)
    

    # Sidebar footer
    st.markdown('<div class="sidebar-footer">', unsafe_allow_html=True)
    if st.button(" Settings", key="menu_settings", use_container_width=True):
        st.session_state.current_menu = "Settings"
        st.rerun()
    if st.button(" Logout", key="menu_logout", use_container_width=True):
        st.success("Logged out successfully!")
    st.markdown('</div>', unsafe_allow_html=True)


# --- MAIN APP VIEW ROUTING ---
if st.session_state.current_menu != "Troubleshooting":
    # Fallback view for other tabs
    st.title(f"{st.session_state.current_menu}")
    st.write(f"This is a placeholder page for the **{st.session_state.current_menu}** module.")
    if st.button("Return to Troubleshooting", key="btn_return"):
        st.session_state.current_menu = "Troubleshooting"
        st.rerun()

elif st.session_state.page == "input":
    # --- INPUT PAGE ---
    
    # Header Title
    st.title("AI Troubleshooting Agent")
    
    # Breadcrumbs (Dynamic highlight based on state)
    docs_active = "active" if len(st.session_state.uploaded_docs_list) > 0 else ""
    logs_active = "active" if st.session_state.log_text != "" else ""
    matches_active = "active" if st.session_state.search_triggered else ""
    res_active = "active" if st.session_state.page == "execution" else ""
    
    st.markdown(f"""
    <div class="pills-container">
        <span class="pill {docs_active or 'active'}">Upload docs</span>
        <span class="pill-dot">·</span>
        <span class="pill {logs_active}">paste logs</span>
        <span class="pill-dot">·</span>
        <span class="pill {matches_active}">generate matches</span>
        <span class="pill-dot">·</span>
        <span class="pill {res_active}">select resolution</span>
    </div>
    """, unsafe_allow_html=True)
    
    # Two Columns Layout (Left = config & inputs, Right = main workspace)
    left_col, right_col = st.columns([1, 2], gap="large")
    
    with left_col:
        # 1. DOC UPLOAD
        st.markdown("""
        <div class="card-header-standalone">
            <i class="fa-regular fa-file-lines" style="margin-right: 6px;"></i>DOC UPLOAD
        </div>
        """, unsafe_allow_html=True)
        
        # Native File Uploader styled directly via global testid override
        uploaded_files = st.file_uploader(
            "Upload docs",
            accept_multiple_files=True,
            label_visibility="collapsed",
            key="doc_file_uploader"
        )
        if uploaded_files:
            st.session_state.uploaded_docs_list = [f.name for f in uploaded_files]
            st.markdown(f"""
            <div style="font-size:0.75rem; color:#10b981; margin-top: -8px; margin-bottom: 12px; padding-left: 10px;">
                <i class="fa-solid fa-circle-check"></i> {len(uploaded_files)} document(s) uploaded
            </div>
            """, unsafe_allow_html=True)

            
        # 2. SIMPLE UPLOAD SAMPLE BUTTON
        st.write("")
        if st.button("Upload Sample", key="btn_sample", use_container_width=True):
            sample_log = (
                "2026-06-07T00:10:45.192Z [error] 2910#0: *12041 "
                "client intended to send too large body: 24910248 bytes, "
                "client: 10.12.94.18, server: api.debugger.local, "
                "request: \"POST /v1/models/analyze HTTP/1.1\", host: \"api.debugger.local\""
            )
            set_log_text(sample_log)
            st.rerun()

        # 3. TESTING MODE CARD (SSH & EXISTING DOCS)
        st.markdown("""
        <div class="custom-card">
            <div class="card-header">
                <span><i class="fa-solid fa-vial card-header-icon"></i>TESTING MODE</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        live_ssh = st.checkbox("Live SSH session", value=st.session_state.ssh_connected, key="live_ssh_checkbox")
        use_existing_docs = st.checkbox("Use existing docs", key="use_existing")
        
        # SSH Creds form if Live SSH is selected
        if live_ssh:
            st.markdown('<div class="ssh-input-label">SSH Credentials</div>', unsafe_allow_html=True)
            ssh_host = st.text_input("Host Address", placeholder="e.g. 192.168.1.100", value=st.session_state.ssh_host, key="ssh_host_input")
            ssh_user = st.text_input("Username", placeholder="e.g. root", value=st.session_state.ssh_username, key="ssh_user_input")
            ssh_pass = st.text_input("Password / Key Path", type="password", key="ssh_pass_input")
            
            col1, col2 = st.columns([2, 1])
            with col1:
                if st.button("Connect SSH", key="btn_connect_ssh", use_container_width=True):
                    if ssh_host and ssh_user:
                        st.session_state.ssh_host = ssh_host
                        st.session_state.ssh_username = ssh_user
                        st.session_state.ssh_connecting = True
                    else:
                        st.error("Please provide Host and Username.")
            with col2:
                if st.session_state.ssh_connected:
                    st.markdown('<span style="color:#10b981; font-size:0.8rem; font-weight:600;"><i class="fa-solid fa-circle-nodes"></i> Connected</span>', unsafe_allow_html=True)
                else:
                    st.markdown('<span style="color:#ef4444; font-size:0.8rem; font-weight:600;"><i class="fa-solid fa-circle-xmark"></i> Offline</span>', unsafe_allow_html=True)
            
            # Simulated connecting loader sequence
            if st.session_state.ssh_connecting:
                with st.spinner("Establishing SSH connection..."):
                    time.sleep(1.2)
                st.toast("SSH Session Established!", icon="🔑")
                st.session_state.ssh_connected = True
                st.session_state.ssh_connecting = False
                
                # Automatically fetch ssh log and insert it
                ssh_mock_log = (
                    "Jun  7 00:10:45 core-prod-node sshd[19082]: Connection closed by "
                    "authenticating user admin 10.12.94.18 port 48922 [preauth]\n"
                    "Jun  7 00:10:48 core-prod-node sshd[19085]: Failed password for "
                    "invalid user admin from 10.12.94.18 port 48928 ssh2"
                )
                set_log_text(ssh_mock_log)
                st.rerun()
            
        # 4. AGENT STATUS BAR
        st.markdown("<div style='margin-top: 1rem;'>", unsafe_allow_html=True)
        st.markdown(f"""
        <div class="status-bar-container">
            <div class="status-dot"></div>
            <div>Agent ready for input... {"(SSH Active)" if st.session_state.ssh_connected else ""}</div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
        
    with right_col:
        # Header Row above the Log text area (Title on left, Trash on rightmost)
        with st.container(key="log_header_container"):
            col_hdr_1, col_hdr_2 = st.columns([12, 1])
            with col_hdr_1:
                st.markdown("""
                <div style="font-size: 0.75rem; font-weight: 700; color: #8fa0dd; text-transform: uppercase; letter-spacing: 1px; display: flex; align-items: center; height: 38px;">
                    <i class="fa-solid fa-terminal" style="margin-right: 8px;"></i>LOG TEXT BOX
                </div>
                """, unsafe_allow_html=True)
            with col_hdr_2:
                if st.button("🗑️", key="btn_clear", help="Clear log entry"):
                    clear_logs()
                    st.rerun()
                
        # Main text area
        log_input = st.text_area(
            "Paste Logs",
            value=st.session_state.log_text,
            placeholder="Paste your server logs, application stack traces, or terminal output here for instant analysis...",
            height=260,
            label_visibility="collapsed",
            key="log_text_area"
        )
        if log_input != st.session_state.log_text:
            st.session_state.log_text = log_input
        col_s1, col_s2 = st.columns([6, 1])
        with col_s2:
            if st.button("Search", key="btn_search_submit", type="primary", use_container_width=True):
                trigger_search(uploaded_files)
                st.rerun()
                
        # SEARCH RESULTS (Dynamic Card under search)
        if st.session_state.search_triggered:
            st.markdown("---", unsafe_allow_html=True)
            st.markdown("### Troubleshooting Steps Matches", unsafe_allow_html=True)
            
            # Engine search status indicator
            api_key = st.session_state.get("gemini_api_key", os.environ.get("GEMINI_API_KEY", os.environ.get("GOOGLE_API_KEY", "")))
            if api_key:
                st.markdown("<div style='font-size:0.75rem; color:#8ab4f8; margin-top: -6px; margin-bottom: 12px; padding-left: 4px;'><i class='fa-solid fa-sparkles'></i> Gemini Semantic LLM Matcher Active</div>", unsafe_allow_html=True)
            else:
                st.markdown("<div style='font-size:0.75rem; color:#64748b; margin-top: -6px; margin-bottom: 12px; padding-left: 4px;'><i class='fa-solid fa-magnifying-glass'></i> Keyword Matcher Active (Enter Gemini API Key in sidebar for semantic LLM match)</div>", unsafe_allow_html=True)
            
            # 2 Columns based on progressive verification workflow
            ts_col_list, ts_col_desc = st.columns([1.1, 1.7], gap="medium")
            
            with ts_col_list:
                with st.container(key="ts_matches_card"):
                    st.markdown("""
                    <div class="card-header" style="border-bottom: 1px solid rgba(255, 255, 255, 0.04); padding-bottom: 8px; margin-bottom: 8px;">
                        <span><i class="fa-solid fa-list-check card-header-icon"></i>TS MATCHES</span>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    if not st.session_state.search_results:
                        st.markdown("<div style='font-size:0.8rem; color:#64748b; padding:10px;'>No matching troubleshooting steps found. Try refining your logs query.</div>", unsafe_allow_html=True)
                    else:
                        with st.container(key="ts_matches_scroll"):
                            for idx, step in enumerate(st.session_state.search_results):
                                is_selected = (st.session_state.selected_ts_idx == idx)
                                key_prefix = "ts_btn_sel" if is_selected else "ts_btn"
                                
                                # Format button text nicely for the card: Title, Score & Source doc
                                label = f"**{step['title']}**\n{step['confidence']} Match • Source: {step['document_name']}\n{step['summary'][:60]}..."
                                
                                if st.button(label, key=f"{key_prefix}_{idx}", use_container_width=True):
                                    st.session_state.selected_ts_idx = idx
                                    st.rerun()
                
            with ts_col_desc:
                if st.session_state.search_results:
                    active_ts = st.session_state.search_results[st.session_state.selected_ts_idx]
                    
                    # Section 1: Incident Verification & Root Cause
                    st.markdown(f"""
                    <div class="custom-card" style="margin-bottom: 16px;">
                        <div class="card-header">
                            <span><i class="fa-solid fa-shield-halved card-header-icon"></i>STEP 1: INCIDENT MATCH VERIFICATION</span>
                        </div>
                        <div class="ts-desc-container" style="height: auto; max-height: 250px;">
                            <div class="ts-desc-title">{active_ts['title']}</div>
                            <div style="font-size:0.75rem; color:#8ab4f8; margin-bottom: 8px; border-bottom: 1px solid rgba(255, 255, 255, 0.04); padding-bottom: 6px;">
                                <i class="fa-regular fa-file"></i> Document Source: <b>{active_ts['document_name']}</b> ({active_ts['confidence']} Match)
                            </div>
                            <div class="ts-desc-section">
                                <div class="ts-desc-label">Detected Root Cause</div>
                                <div class="ts-desc-text">{active_ts['cause']}</div>
                            </div>
                            <div class="ts-desc-section">
                                <div class="ts-desc-label">Issue Summary Context</div>
                                <div class="ts-desc-text">{active_ts['summary']}</div>
                            </div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # Extract and display timestamped logs evidence
                    matched_entries = extract_timestamped_logs(st.session_state.log_text, active_ts['match_trigger'])
                    
                    st.markdown("<div style='margin-top:-8px; margin-bottom:12px; padding: 0 4px;'>", unsafe_allow_html=True)
                    st.markdown("<span style='color:#64748b; font-size:0.7rem; text-transform:uppercase; font-weight:700; display:block; margin-bottom:6px;'>Verification Log Analysis</span>", unsafe_allow_html=True)
                    for entry in matched_entries:
                        st.markdown(f"""
                        <div style='background-color:#090c12; border:1px solid #1e293b; border-radius:6px; padding:8px 12px; margin-bottom:6px; font-family:"Fira Code", monospace; font-size:0.75rem;'>
                            <span style='color:#8ab4f8; font-weight:600;'>[{entry['timestamp']}]</span> {entry['message']}
                        </div>
                        """, unsafe_allow_html=True)
                    st.markdown("</div>", unsafe_allow_html=True)
                    
                    # Section 2: Proposed Resolution Plan & Execution (displayed directly)
                    st.markdown(f"""
                    <div class="custom-card" style="border-color: rgba(16, 185, 129, 0.3); margin-top: 16px;">
                        <div class="card-header" style="color: #10b981;">
                            <span><i class="fa-solid fa-heart-pulse card-header-icon"></i>STEP 2: PROPOSED RESOLUTION PLAN</span>
                        </div>
                        <div class="ts-desc-container" style="height: auto; max-height: 250px;">
                            <div class="ts-desc-section">
                                <div class="ts-desc-label" style="color: #10b981;">Proposed Resolution Steps</div>
                                <div class="ts-desc-text" style="color: #ffffff;">{active_ts['resolution']}</div>
                            </div>
                            <div class="ts-desc-section">
                                <div class="ts-desc-label">Recovery Script Commands</div>
                                <div style="font-family:'Fira Code', monospace; font-size:0.75rem; background-color:#0c1017; border:1px solid #1a2233; border-radius:6px; padding:8px; color:#cbd5e1; white-space:pre-wrap; line-height:1.4;">""" + "\n".join([f"$ {cmd}" for cmd in active_ts['commands']]) + """</div>
                            </div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # Generate Button Card to proceed to execution page
                    st.markdown("<div style='background-color:rgba(138, 180, 248, 0.03); border: 1px solid rgba(138, 180, 248, 0.1); border-radius:8px; padding:12px; margin-top:16px;'>", unsafe_allow_html=True)
                    col_ex1, col_ex2 = st.columns([3.2, 1.8])
                    with col_ex1:
                        st.markdown("""
                        <div style='font-size:0.8rem; line-height:1.3;'>
                            <b>Generate Resolution Script</b><br>
                            <span style='color:#94a3b8; font-size:0.75rem;'>Generate a bash execution script based on the resolution steps.</span>
                        </div>
                        """, unsafe_allow_html=True)
                    with col_ex2:
                        if st.button("⚡ Generate", key="btn_generate_resolution", type="primary", use_container_width=True):
                            st.session_state.page = "execution"
                            initialize_execution_state(active_ts)
                            st.rerun()
                    st.markdown("</div>", unsafe_allow_html=True)
                else:
                    st.markdown("""
                    <div class="custom-card" style="height: 350px;">
                        <div class="card-header">
                            <span><i class="fa-solid fa-circle-info card-header-icon"></i>STEP DESCRIPTION</span>
                        </div>
                        <div style="font-size:0.8rem; color:#64748b; padding:10px;">Select a match to view details.</div>
                    </div>
                    """, unsafe_allow_html=True)
 
        # CONTINUATION / BOTTOM BAR (Refine or Ask follow-up)
        st.write("")
        with st.container(key="bottom_bar_container"):
            col_b1, col_b2 = st.columns([5, 1])
            with col_b1:
                refinement_val = st.text_input(
                    "Ask follow-up",
                    placeholder="Ask a follow-up question or refine the analysis...",
                    key="refinement_input",
                    label_visibility="collapsed"
                )
            with col_b2:
                # Generate button on bottom-right matching layout image
                if st.button("⚡ Generate", key="btn_generate_bottom", type="primary"):
                    st.session_state.page = "execution"
                    selected_ts = st.session_state.search_results[st.session_state.selected_ts_idx] if st.session_state.search_results else MOCK_TS_STEPS[0]
                    initialize_execution_state(selected_ts)
                    st.rerun()
        if refinement_val and refinement_val != st.session_state.refinement:
            st.session_state.refinement = refinement_val
            combined_query = st.session_state.log_text + "\n" + refinement_val
            st.session_state.search_results = execute_search(combined_query, uploaded_files)
            st.session_state.search_triggered = True
            st.session_state.selected_ts_idx = 0
            st.rerun()
        if st.session_state.refinement:
            st.markdown(f"""
            <div style="font-size:0.75rem; color:#8ab4f8; margin-top: 4px; padding-left: 10px;">
                <i class="fa-regular fa-lightbulb"></i> Refinement active: "{st.session_state.refinement}"
            </div>
            """, unsafe_allow_html=True)
 
else:
    # --- PAGE 2: EXECUTION DASHBOARD (TROUBLESHOOTING RESOLUTION) ---
    selected_ts = st.session_state.search_results[st.session_state.selected_ts_idx] if st.session_state.search_results else MOCK_TS_STEPS[0]
    if not st.session_state.get("generated_bash_script"):
        initialize_execution_state(selected_ts)
        
    st.markdown('<div class="execution-header">', unsafe_allow_html=True)
    st.title("⚡ Resolution Execution Dashboard")
    st.markdown(f"""
    <div class="pills-container">
        <span class="pill">Upload docs</span>
        <span class="pill-dot">·</span>
        <span class="pill">paste logs</span>
        <span class="pill-dot">·</span>
        <span class="pill">generate matches</span>
        <span class="pill-dot">·</span>
        <span class="pill active">Executing Resolution: {selected_ts['id']}</span>
    </div>
    """, unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    col_exec1, col_exec2 = st.columns([1.1, 0.9], gap="large")
    
    with col_exec1:
        # 1. Selected troubleshooting heading display
        st.markdown(f"""
        <div class="heading-display-card">
            <div class="heading-display-title">Selected Troubleshooting Heading</div>
            <div class="heading-display-value">{selected_ts.get('title', 'Unknown Step')}</div>
        </div>
        """, unsafe_allow_html=True)
        
        # 2. Bash Script Code Block
        st.markdown("""
        <div style="font-size: 0.75rem; font-weight: 700; color: #8fa0dd; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px;">
            <i class="fa-solid fa-file-code" style="margin-right: 6px;"></i>Generated Bash Script
        </div>
        """, unsafe_allow_html=True)
        st.code(st.session_state.generated_bash_script, language="bash")
        
        # 3. Prompt textbox for feedback
        st.markdown("""
        <div style="font-size: 0.75rem; font-weight: 700; color: #8fa0dd; text-transform: uppercase; letter-spacing: 1px; margin-top: 12px; margin-bottom: 6px;">
            <i class="fa-solid fa-pen-to-square" style="margin-right: 6px;"></i>Feedback to edit script
        </div>
        """, unsafe_allow_html=True)
        
        st.text_input(
            "Feedback to edit script",
            placeholder="Type feedback or prompt to edit script and press Enter...",
            key="script_feedback_input",
            on_change=handle_feedback,
            label_visibility="collapsed"
        )
        
        # Space separator
        st.write("")
        
        # 4. Conditional Approval Dialog Modal
        import re
        vulnerable_commands = ["rm", "dd", "mv", "remove", "delete"]
        is_vulnerable = any(re.search(rf"\b{cmd}\b", st.session_state.generated_bash_script.lower()) for cmd in vulnerable_commands)
        
        if st.session_state.show_approve_modal:
            st.markdown('<div class="approve-dialog-box">', unsafe_allow_html=True)
            if is_vulnerable:
                st.markdown(
                    """
                    <div class="dialog-warning-header">
                        <i class="fa-solid fa-triangle-exclamation"></i> VULNERABLE CODE WARNING
                    </div>
                    <div class="dialog-text">
                        This script contains potentially destructive commands (e.g., <code>rm</code>, <code>dd</code>, <code>mv</code>, <code>remove</code>, or <code>delete</code>). 
                        Are you sure you want to approve this bash code to execute?
                    </div>
                    """, 
                    unsafe_allow_html=True
                )
                col_m1, col_m2 = st.columns(2)
                with col_m1:
                    if st.button("Yes, Approve anyway", key="btn_confirm_vulnerable_approve", type="primary", use_container_width=True):
                        st.session_state.script_approved = True
                        st.session_state.show_approve_modal = False
                        st.toast("Script approved with warning bypass.", icon="⚠️")
                        st.rerun()
                with col_m2:
                    if st.button("Cancel", key="btn_cancel_vulnerable_approve", use_container_width=True):
                        st.session_state.show_approve_modal = False
                        st.rerun()
            else:
                st.markdown(
                    """
                    <div class="dialog-info-header">
                        <i class="fa-solid fa-circle-question"></i> CONFIRM APPROVAL
                    </div>
                    <div class="dialog-text">
                        Are you sure you want to approve this resolution script for execution on the VM?
                    </div>
                    """, 
                    unsafe_allow_html=True
                )
                col_m1, col_m2 = st.columns(2)
                with col_m1:
                    if st.button("Yes, Approve", key="btn_confirm_approve", type="primary", use_container_width=True):
                        st.session_state.script_approved = True
                        st.session_state.show_approve_modal = False
                        st.toast("Script approved successfully.", icon="✅")
                        st.rerun()
                with col_m2:
                    if st.button("Cancel", key="btn_cancel_approve", use_container_width=True):
                        st.session_state.show_approve_modal = False
                        st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)
            
        # 5. Bottom Action Buttons
        col_act1, col_act2, col_act3 = st.columns(3)
        with col_act1:
            if st.button("Back", key="btn_back", use_container_width=True):
                st.session_state.page = "input"
                # Reset Page 2 state
                st.session_state.generated_bash_script = ""
                st.session_state.script_approved = False
                st.session_state.show_approve_modal = False
                st.session_state.execution_started = False
                st.session_state.execution_completed = False
                st.session_state.console_logs = []
                st.rerun()
        with col_act2:
            approve_label = "Approved ✅" if st.session_state.script_approved else "Approve"
            if st.button(approve_label, key="btn_approve", use_container_width=True):
                st.session_state.show_approve_modal = True
                st.rerun()
        with col_act3:
            execute_disabled = not st.session_state.script_approved
            if st.button("Execute", key="btn_execute", type="primary", disabled=execute_disabled, use_container_width=True):
                st.session_state.execution_started = True
                st.session_state.execution_completed = False
                st.session_state.console_logs = []
                st.rerun()
                
    with col_exec2:
        # 6. Code execution logs
        st.markdown("""
        <div style="font-size: 0.75rem; font-weight: 700; color: #8fa0dd; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px;">
            <i class="fa-solid fa-terminal" style="margin-right: 6px;"></i>Code Execution Logs
        </div>
        """, unsafe_allow_html=True)
        
        console_placeholder = st.empty()
        
        def render_console(lines):
            html = '<div class="console-output-card">'
            for l in lines:
                html += f'<div class="console-line">{l}</div>'
            html += '</div>'
            console_placeholder.markdown(html, unsafe_allow_html=True)
            
        # 7. Verification results
        # Decide if we execute simulation or render static
        if st.session_state.execution_started and not st.session_state.execution_completed:
            # Run simulation
            # Parse commands
            lines = st.session_state.generated_bash_script.split("\n")
            commands_to_run = []
            for line in lines:
                line_stripped = line.strip()
                if not line_stripped or line_stripped.startswith("#") or line_stripped.startswith("if ") or line_stripped.startswith("fi") or line_stripped == "then" or line_stripped.startswith("else"):
                    continue
                if line_stripped.startswith("echo "):
                    echo_text = line_stripped[5:].strip("'\"")
                    commands_to_run.append({"type": "echo", "text": echo_text})
                else:
                    commands_to_run.append({"type": "cmd", "text": line_stripped})
                    
            console_lines = [
                '<span class="console-info">[SYSTEM] Initializing VM Connection...</span>'
            ]
            render_console(console_lines)
            time.sleep(0.6)
            
            if st.session_state.ssh_host:
                console_lines.append(f'<span class="console-info">[SYSTEM] Connecting to SSH Host: {st.session_state.ssh_host} as user: {st.session_state.ssh_username}...</span>')
            else:
                console_lines.append('<span class="console-info">[SYSTEM] Connecting to Local Sandbox VM...</span>')
            render_console(console_lines)
            time.sleep(0.8)
            
            console_lines.append('<span class="console-success">[SUCCESS] Connection established. Socket active.</span>')
            render_console(console_lines)
            time.sleep(0.4)
            
            console_lines.append('<span class="console-info">[SYSTEM] Transferring resolution script (resolve_incident.sh)...</span>')
            render_console(console_lines)
            time.sleep(0.5)
            
            console_lines.append('<span class="console-info">[SYSTEM] Execution started: bash resolve_incident.sh</span>')
            render_console(console_lines)
            time.sleep(0.6)
            
            for idx, c in enumerate(commands_to_run):
                if c["type"] == "echo":
                    console_lines.append(f'<span class="console-info">[INFO] {c["text"]}</span>')
                    render_console(console_lines)
                    time.sleep(0.4)
                elif c["type"] == "cmd":
                    console_lines.append(f'<span class="console-cmd">$ {c["text"]}</span>')
                    render_console(console_lines)
                    time.sleep(0.7)
                    
                    cmd_text = c["text"].lower()
                    if "nginx -t" in cmd_text:
                        console_lines.append('<span class="console-success">[SUCCESS] nginx: configuration file syntax is ok. test is successful.</span>')
                    elif "systemctl reload" in cmd_text or "restart" in cmd_text:
                        console_lines.append('<span class="console-success">[SUCCESS] Service restarted successfully. PID reallocated.</span>')
                    elif "chmod" in cmd_text or "chown" in cmd_text:
                        console_lines.append('<span class="console-success">[SUCCESS] File permissions modified and verified.</span>')
                    elif "rm" in cmd_text or "dd" in cmd_text or "mv" in cmd_text or "delete" in cmd_text or "remove" in cmd_text:
                        console_lines.append('<span class="console-success">[SUCCESS] Path cleaned/moved. Space reallocated.</span>')
                    elif "sed" in cmd_text or "grep" in cmd_text or "cat" in cmd_text:
                        console_lines.append('<span class="console-info">[INFO] Target file modified/scanned.</span>')
                    else:
                        console_lines.append('<span class="console-info">[INFO] Command executed with exit code 0.</span>')
                    
                    render_console(console_lines)
                    time.sleep(0.4)
            
            console_lines.append('<span class="console-info">[SYSTEM] Verifying post-conditions...</span>')
            render_console(console_lines)
            time.sleep(0.6)
            
            console_lines.append('<span class="console-success">[SUCCESS] Verification test suite passed (3/3 checks ok).</span>')
            console_lines.append('<span class="console-success"><b>[COMPLETE] Incident successfully resolved!</b></span>')
            render_console(console_lines)
            
            st.session_state.console_logs = console_lines
            st.session_state.execution_completed = True
            st.rerun()
            
        elif st.session_state.execution_completed:
            render_console(st.session_state.console_logs)
            
            # 8. Verification results display
            st.markdown(f"""
            <div class="verification-result-card">
                <div class="verification-result-header">
                    <i class="fa-solid fa-shield-check" style="margin-right: 6px; color: #10b981;"></i>VERIFICATION RESULT
                </div>
                <div class="verification-result-body">
                    <div class="result-item"><span class="result-label">System Health Status:</span> <span class="result-value val-healthy">100% HEALTHY</span></div>
                    <div class="result-item"><span class="result-label">Log Verification:</span> <span class="result-value">Errors cleared (0 new warnings)</span></div>
                    <div class="result-item"><span class="result-label">Service Connectivity:</span> <span class="result-value">Verifying TCP handshake: OK (12ms)</span></div>
                    <div class="result-item" style="border-top: 1px solid rgba(255, 255, 255, 0.04); padding-top: 8px; margin-top: 8px;">
                        <span class="result-label">Resolution Summary:</span>
                        <div class="result-summary-text">{selected_ts.get('resolution', 'No resolution details provided.')}</div>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
        else:
            # Ready but not started
            console_lines = ['<span class="console-info">[SYSTEM] Console ready. Waiting for execution...</span>']
            render_console(console_lines)
            
            st.markdown(f"""
            <div class="verification-result-card card-disabled">
                <div class="verification-result-header" style="color: #64748b;">
                    <i class="fa-solid fa-shield-halved" style="margin-right: 6px;"></i>VERIFICATION RESULT
                </div>
                <div class="verification-result-body" style="color: #64748b; font-style: italic;">
                    Verification results will be displayed here after script execution.
                </div>
            </div>
            """, unsafe_allow_html=True)
