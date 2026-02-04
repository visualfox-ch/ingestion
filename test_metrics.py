#!/usr/bin/env python3
"""Quick test of /metrics endpoint"""
import sys
sys.path.insert(0, '.')

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)

# Test /metrics endpoint
print('Testing /metrics endpoint...')
response = client.get('/metrics')
print(f'Status: {response.status_code}')
print(f'Content-Type: {response.headers.get("content-type")}')

content = response.text
has_help = '# HELP' in content
has_type = '# TYPE' in content
has_red_agent = 'red_agent_requests_total' in content

print(f'Has HELP lines: {has_help}')
print(f'Has TYPE lines: {has_type}')
print(f'Has red_agent metrics: {has_red_agent}')

if has_help and has_type and has_red_agent:
    print('✅ /metrics endpoint working correctly!')
    print(f'\nOutput sample (first 800 chars):\n')
    print(content[:800])
else:
    print('❌ Metrics endpoint not producing expected format')
    print('\nFirst 1000 chars:\n')
    print(content[:1000])
