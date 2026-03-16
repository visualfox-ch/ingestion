#!/bin/bash
# Run pytest with coverage and output HTML report
pytest --cov=app --cov-report=html --cov-report=term
