# Testskript für Asana-API-Endpunkte (lokal)
# Führt einfache GET-Requests gegen die FastAPI-Endpoints aus

import requests

BASE_URL = "http://192.168.1.103:18000"  # NAS-IP und Port

print("--- Projekte ---")
resp = requests.get(f"{BASE_URL}/asana/projects")
print(resp.status_code, resp.json())

print("--- Workspaces ---")
resp = requests.get(f"{BASE_URL}/asana/workspaces")
print(resp.status_code, resp.json())

print("--- Tasks (alle) ---")
resp = requests.get(f"{BASE_URL}/asana/tasks")
print(resp.status_code, resp.json())

# Beispiel: Tasks für ein bestimmtes Projekt (ID anpassen)
# project_id = "1234567890"
# resp = requests.get(f"{BASE_URL}/asana/tasks", params={"project_id": project_id})
# print(resp.status_code, resp.json())
