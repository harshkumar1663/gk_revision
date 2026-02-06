#!/usr/bin/env python3
"""
Script to batch add geography lectures to the SSC GK Tracker
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add the app directory to path to import functions
sys.path.insert(0, '/media/harsh/Projects/Quizz')

from app.main import calculate_revision_dates, format_date_for_storage

DATA_FILE = Path("/media/harsh/Projects/Quizz/gk_data.json")

# Lecture data: (date_str, name)
LECTURES = [
    ("26/12/2025", "Solar System"),
    ("27/12/2025", "Latitude and Longitude"),
    ("28/12/2025", "Earth Interior and Tectonics"),
    ("29/12/2025", "Continent and Oceans"),
    ("30/12/2025", "Rocks and Volcano"),
    ("01/01/2026", "Geomorphic Process"),
    ("02/01/2026", "Landforms"),
    ("03/01/2026", "Atmosphere"),
    ("04/01/2026", "Condensation and Precipitation"),
    ("05/01/2026", "Winds"),
    ("06/01/2026", "Cyclone and Ocean Current"),
    ("09/01/2026", "India and Its Location"),
    ("10/01/2026", "Himalayas"),
    ("11/01/2026", "Peninsular Plateau"),
    ("12/01/2026", "Plains and Islands"),
    ("13/01/2026", "Himalayan River System"),
    ("14/01/2026", "Peninsular River System"),
    ("17/01/2026", "Dams Lakes and Waterfalls"),
]

DIFFICULTY = 3
CATEGORY = "Geography"


def load_data():
    """Load data from JSON file"""
    if not DATA_FILE.exists():
        print("Error: Data file not found. Please set exam date in the app first.")
        return None
    
    with open(DATA_FILE, 'r') as f:
        return json.load(f)


def save_data(data):
    """Save data to JSON file"""
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)


def add_lectures():
    """Add all lectures to the data file"""
    data = load_data()
    
    if not data:
        return
    
    if not data.get("exam_date"):
        print("Error: Exam date not set. Please set it in the app first.")
        return
    
    print(f"Exam date: {data['exam_date']}")
    print(f"\nAdding {len(LECTURES)} lectures...\n")
    
    added_count = 0
    
    for date_str, name in LECTURES:
        # Parse date DD/MM/YYYY
        study_date_obj = datetime.strptime(date_str, "%d/%m/%Y")
        study_date = format_date_for_storage(study_date_obj)
        
        # Create unique lecture ID
        lecture_id = f"lecture_{datetime.now().timestamp()}_{added_count}"
        
        # Calculate revision dates
        revision_dates = calculate_revision_dates(
            study_date,
            data["exam_date"],
            DIFFICULTY
        )
        
        # Add lecture
        data["lectures"][lecture_id] = {
            "name": name,
            "study_date": study_date,
            "difficulty": DIFFICULTY,
            "category": CATEGORY,
            "revision_dates": revision_dates
        }
        
        print(f"✓ Added: {name} (Study: {date_str}) - {len(revision_dates)} revision stages")
        added_count += 1
    
    # Save data
    save_data(data)
    
    print(f"\n✅ Successfully added {added_count} lectures for both Harsh and Divya!")
    print(f"📁 Data saved to: {DATA_FILE}")


if __name__ == "__main__":
    add_lectures()
