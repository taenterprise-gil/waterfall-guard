import streamlit as st
import streamlit.components.v1 as components

LOGO_URL = (
    "https://uurrjcsvdtprnpfqpver.supabase.co/storage/v1/object/public/"
    "openclaw%20claim%20recovery%20project/logo%20(1).png"
)

HTML_CONTENT = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<style>
  body {{
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #0f172a;
    color: #e2e8f0;
  }}
  .header {{
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 20px 24px;
    background: #1e293b;
    border-bottom: 1px solid #334155;
  }}
  .header img {{
    height: 48px;
    width: auto;
  }}
  .header h1 {{
    font-size: 20px;
    margin: 0;
  }}
  .content {{
    padding: 24px;
  }}
</style>
</head>
<body>
  <div class="header">
    <img src="{LOGO_URL}" alt="OpenClaw logo" />
    <h1>OpenClaw Dashboard</h1>
  </div>
  <div class="content">
    <p>Dashboard content goes here.</p>
  </div>
</body>
</html>
"""

# Streamlit Gated Entry Point
components.html(HTML_CONTENT, height=1000, scrolling=True)
