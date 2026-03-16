import requests
from flask import Blueprint, render_template, request, redirect, url_for, flash

reload_bp = Blueprint('reload_skills', __name__)

RELOAD_ENDPOINT = "http://localhost:18000/skills/reload"

@reload_bp.route('/reload-skills', methods=['POST'])
def reload_skills():
    try:
        resp = requests.post(RELOAD_ENDPOINT)
        flash(f"Skills reloaded: {resp.json().get('skills')}", "success")
    except Exception as e:
        flash(f"Reload failed: {e}", "danger")
    return redirect(url_for('dashboard.index'))

# Add a button in your dashboard template:
# <form action="{{ url_for('reload_skills.reload_skills') }}" method="post">
#     <button type="submit">Reload Skills</button>
# </form>
