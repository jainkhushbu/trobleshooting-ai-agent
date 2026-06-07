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

# Helper functions
def set_log_text(text):
    st.session_state.log_text = text
    st.session_state.search_triggered = False

def clear_logs():
    st.session_state.log_text = ""
    st.session_state.search_triggered = False

def trigger_search():
    if st.session_state.log_text.strip():
        st.session_state.search_triggered = True
        # Try to match the best TS based on content
        content = st.session_state.log_text.lower()
        matched = False
        for idx, ts in enumerate(MOCK_TS_STEPS):
            if ts["match_trigger"].lower() in content:
                st.session_state.selected_ts_idx = idx
                matched = True
                break
        if not matched:
            st.session_state.selected_ts_idx = 0 # default to first
    else:
        st.session_state.search_triggered = False

def handle_refinement():
    if st.session_state.refinement_input:
        st.session_state.refinement = st.session_state.refinement_input
        # Adjust confidence/selection slightly based on refinement
        ref_text = st.session_state.refinement.lower()
        for idx, ts in enumerate(MOCK_TS_STEPS):
            if ts["id"].lower() in ref_text or ts["match_trigger"].lower() in ref_text:
                st.session_state.selected_ts_idx = idx
                break
        st.session_state.search_triggered = True

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
    if st.button("+ New Session", key="btn_new"):
        st.session_state.page = "input"
        st.session_state.log_text = ""
        st.session_state.search_triggered = False
        st.session_state.selected_ts_idx = 0
        st.session_state.ssh_connected = False
        st.session_state.uploaded_docs_list = []
        st.session_state.refinement = ""
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
        # 1. DOC UPLOAD CARD
        st.markdown("""
        <div class="custom-card">
            <div class="card-header">
                <span><i class="fa-solid fa-file-arrow-up card-header-icon"></i>DOC UPLOAD</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        # Native File Uploader nested inside Card area
        uploaded_files = st.file_uploader(
            "Upload docs",
            accept_multiple_files=True,
            label_visibility="collapsed"
        )
        if uploaded_files:
            st.session_state.uploaded_docs_list = [f.name for f in uploaded_files]
            st.markdown(f"""
            <div style="font-size:0.75rem; color:#10b981; margin-top: -10px; margin-bottom: 10px;">
                <i class="fa-solid fa-circle-check"></i> {len(uploaded_files)} document(s) uploaded
            </div>
            """, unsafe_allow_html=True)
            
        # 2. SAMPLE OUTPUT CARD
        st.markdown("""
        <div class="custom-card">
            <div class="card-header">
                <span><i class="fa-solid fa-code card-header-icon"></i>SAMPLE OUTPUT</span>
            </div>
            <div class="code-preview">// Expected pattern
HTTP 200 { "status": "ok" }
Connection: keep-alive
Server: nginx/1.21.6</div>
        </div>
        """, unsafe_allow_html=True)
        
        # Prefill Sample Log Button
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
        
        live_ssh = st.checkbox("Live SSH", value=st.session_state.ssh_connected, key="live_ssh_checkbox")
        use_existing_docs = st.checkbox("Use existing docs", key="use_existing")
        
        # SSH Creds form if Live SSH is selected
        if live_ssh:
            st.markdown('<div class="ssh-form">', unsafe_allow_html=True)
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
            st.markdown('</div>', unsafe_allow_html=True)
            
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
        # LOG TEXT BOX CARD
        st.markdown("""
        <div class="custom-card" style="margin-bottom: 20px;">
            <div class="card-header">
                <span><i class="fa-solid fa-terminal card-header-icon"></i>LOG TEXT BOX</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        # Log input container
        st.markdown('<div class="log-textarea-container">', unsafe_allow_html=True)
        # Clear log text button
        col_clear_1, col_clear_2 = st.columns([12, 1])
        with col_clear_2:
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
            
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Search Button row
        col_s1, col_s2 = st.columns([6, 1])
        with col_s2:
            if st.button("Search", key="btn_search_submit", use_container_width=True):
                trigger_search()
                st.rerun()
                
        # SEARCH RESULTS (Dynamic Card under search)
        if st.session_state.search_triggered:
            st.markdown("---", unsafe_allow_html=True)
            st.markdown("### Troubleshooting Steps Matches", unsafe_allow_html=True)
            
            # 3 Columns based on User Image 2 layout: TS scroll list | TS short description | Generate button
            ts_col_list, ts_col_desc, ts_col_btn = st.columns([1.1, 1.3, 0.4], gap="medium")
            
            with ts_col_list:
                st.markdown("""
                <div class="custom-card" style="height: 300px;">
                    <div class="card-header">
                        <span><i class="fa-solid fa-list-check card-header-icon"></i>TS MATCHES</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                # List matching TS elements in a scrollable block
                st.markdown('<div class="ts-scroll-container">', unsafe_allow_html=True)
                
                # Check for active query logs to highlight matching items or show scores
                for idx, step in enumerate(MOCK_TS_STEPS):
                    is_selected = (st.session_state.selected_ts_idx == idx)
                    selected_style = "selected" if is_selected else ""
                    
                    # Custom HTML button that acts as list item card
                    btn_text = f"{step['id']} ({step['confidence']} Match)"
                    if st.button(btn_text, key=f"ts_btn_{idx}", use_container_width=True):
                        st.session_state.selected_ts_idx = idx
                        st.rerun()
                        
                    # Custom markup descriptions details below the button to look exact like screenshot
                    st.markdown(f"""
                    <div class="ts-list-item {selected_style}" style="margin-top: -6px; margin-bottom: 8px; pointer-events: none;">
                        <div class="ts-item-header">
                            <span class="ts-item-title">{step['title']}</span>
                            <span class="ts-item-conf {step['class']}">{step['confidence']}</span>
                        </div>
                        <div class="ts-item-desc-snippet">{step['summary']}</div>
                    </div>
                    """, unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)
                
            with ts_col_desc:
                active_ts = MOCK_TS_STEPS[st.session_state.selected_ts_idx]
                st.markdown(f"""
                <div class="custom-card" style="height: 300px;">
                    <div class="card-header">
                        <span><i class="fa-solid fa-circle-info card-header-icon"></i>STEP DESCRIPTION</span>
                    </div>
                    <div class="ts-desc-container">
                        <div class="ts-desc-title">{active_ts['title']}</div>
                        <div class="ts-desc-section">
                            <div class="ts-desc-label">Issue Summary</div>
                            <div class="ts-desc-text">{active_ts['summary']}</div>
                        </div>
                        <div class="ts-desc-section">
                            <div class="ts-desc-label">Potential Root Cause</div>
                            <div class="ts-desc-text">{active_ts['cause']}</div>
                        </div>
                        <div class="ts-desc-section">
                            <div class="ts-desc-label">Proposed Resolution</div>
                            <div class="ts-desc-text" style="color: #8ab4f8;">{active_ts['resolution']}</div>
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
            with ts_col_btn:
                # Vertical spacer to center align the generate button in column 3
                st.write("")
                st.write("")
                st.write("")
                st.write("")
                st.write("")
                st.write("")
                if st.button("⚡ Generate", key="btn_generate_ts", use_container_width=True):
                    st.session_state.page = "execution"
                    st.rerun()
                st.markdown("""
                <div style="font-size:0.7rem; text-align:center; color:#64748b; margin-top: 10px;">
                    Proceed with the selected resolution path.
                </div>
                """, unsafe_allow_html=True)

        # CONTINUATION / BOTTOM BAR (Refine or Ask follow-up)
        st.write("")
        st.markdown('<div class="bottom-bar">', unsafe_allow_html=True)
        col_b1, col_b2 = st.columns([5, 1])
        with col_b1:
            st.text_input(
                "Ask follow-up",
                placeholder="Ask a follow-up question or refine the analysis...",
                key="refinement_input",
                on_change=handle_refinement,
                label_visibility="collapsed"
            )
        with col_b2:
            # Generate button on bottom-right matching layout image
            if st.button("⚡ Generate", key="btn_generate_bottom"):
                st.session_state.page = "execution"
                st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
        if st.session_state.refinement:
            st.markdown(f"""
            <div style="font-size:0.75rem; color:#8ab4f8; margin-top: 4px; padding-left: 10px;">
                <i class="fa-regular fa-lightbulb"></i> Refinement active: "{st.session_state.refinement}"
            </div>
            """, unsafe_allow_html=True)

else:
    # --- PAGE 2: EXECUTION DASHBOARD (TROUBLESHOOTING RESOLUTION) ---
    selected_ts = MOCK_TS_STEPS[st.session_state.selected_ts_idx]
    
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
    
    col_exec1, col_exec2 = st.columns([1, 2], gap="large")
    
    with col_exec1:
        st.markdown(f"""
        <div class="custom-card">
            <div class="card-header">
                <span><i class="fa-solid fa-file-invoice card-header-icon"></i>TARGET INFO</span>
            </div>
            <div style="font-size:0.85rem; line-height: 1.6;">
                <p><b>Resolution Step:</b> {selected_ts['title']}</p>
                <p><b>Confidence Rating:</b> <span class="ts-item-conf {selected_ts['class']}">{selected_ts['confidence']}</span></p>
                <p><b>Target Environment:</b> {"SSH Host: " + st.session_state.ssh_host if st.session_state.ssh_host else "Simulated Environment"}</p>
                <p><b>User SSH Profile:</b> {st.session_state.ssh_username if st.session_state.ssh_username else "local-debugger"}</p>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        # Progress status widgets
        st.markdown("""
        <div class="custom-card">
            <div class="card-header">
                <span><i class="fa-solid fa-chart-line card-header-icon"></i>EXECUTION PROGRESS</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        prog_bar = st.progress(0)
        status_text = st.empty()
        
        st.write("")
        if st.button("← Return to Workspace", key="btn_back_workspace", use_container_width=True):
            st.session_state.page = "input"
            st.rerun()
            
    with col_exec2:
        st.markdown("""
        <div class="custom-card">
            <div class="card-header">
                <span><i class="fa-solid fa-rectangle-terminal card-header-icon"></i>CONSOLE OUTPUT</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        console_placeholder = st.empty()
        
        # Build live log simulation output
        console_lines = []
        
        def render_console(lines):
            html = '<div class="console-output-card">'
            for l in lines:
                html += f'<div class="console-line">{l}</div>'
            html += '</div>'
            console_placeholder.markdown(html, unsafe_allow_html=True)
            
        # Start command sequences
        console_lines.append('<span class="console-info">[INFO] Initializing Cognitive Debugger Execution Agent...</span>')
        render_console(console_lines)
        time.sleep(0.5)
        
        console_lines.append(f'<span class="console-info">[INFO] Targeting: {st.session_state.ssh_host if st.session_state.ssh_host else "local-sandbox"}</span>')
        render_console(console_lines)
        time.sleep(0.5)
        
        prog_bar.progress(20)
        status_text.text("Status: Analyzing workspace config...")
        
        # Print resolution steps
        for cmd in selected_ts["commands"]:
            console_lines.append(f'<span class="console-cmd">$ {cmd}</span>')
            render_console(console_lines)
            time.sleep(0.8)
            
            # Print mock success of command
            if "chmod" in cmd or "sed" in cmd:
                console_lines.append('<span class="console-success">[SUCCESS] File permissions modified and verified.</span>')
            elif "grep" in cmd or "cat" in cmd:
                console_lines.append(f'<span class="console-warn">[WARN] Found target signature: {selected_ts["match_trigger"]}</span>')
            elif "restart" in cmd or "reload" in cmd:
                console_lines.append('<span class="console-success">[SUCCESS] Service restarted successfully. PID reallocated.</span>')
            elif "nginx -t" in cmd:
                console_lines.append('<span class="console-success">[SUCCESS] nginx: configuration file syntax is ok. test is successful.</span>')
            else:
                console_lines.append('<span class="console-info">[INFO] Command executed with exit code 0.</span>')
                
            render_console(console_lines)
            time.sleep(0.4)
            
        prog_bar.progress(70)
        status_text.text("Status: Running verification tests...")
        
        console_lines.append('<span class="console-info">[INFO] Verifying post-conditions...</span>')
        render_console(console_lines)
        time.sleep(0.8)
        
        console_lines.append('<span class="console-success">[SUCCESS] Verification test suite passed (3/3 checks ok).</span>')
        console_lines.append('<span class="console-success"><b>[COMPLETE] Incident successfully resolved!</b></span>')
        render_console(console_lines)
        
        prog_bar.progress(100)
        status_text.text("Status: Completed. Service is healthy!")
