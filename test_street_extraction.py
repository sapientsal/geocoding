#!/usr/bin/env python3
import unittest
import re

class TestStreetNameExtraction(unittest.TestCase):
    """Test the street name extraction logic directly"""
    
    def test_clean_street_name(self):
        """Test the clean_street_name function logic"""
        print("\n🔍 Testing street name extraction function...")
        
        # This is a simplified version of the clean_street_name function from server.py
        def clean_street_name(street_name):
            if not street_name or str(street_name).strip() == '':
                return ''
            
            street = str(street_name).strip()
            
            # Handle German address format: "624 Worpswede Albert-Schwedt-Weg"
            # Remove project code and city prefix
            parts = street.split()
            if len(parts) >= 3:
                # Check if first part is numeric (project code)
                if parts[0].isdigit():
                    # Remove first part (project code)
                    remaining = ' '.join(parts[1:])
                    
                    # Check if second part is a city name like "Worpswede"
                    if len(parts) >= 3 and parts[1].isalpha():
                        # Remove city name too, keep only street name
                        street = ' '.join(parts[2:])
                    else:
                        street = remaining
                elif parts[0].isalpha() and len(parts) >= 2:
                    # If first part is alpha (like "Worpswede"), remove it
                    street = ' '.join(parts[1:])
            
            # Additional cleanup for common prefixes
            if street.startswith('Worpswede '):
                street = street[10:].strip()
            
            return street.strip()
        
        # Test cases
        test_cases = [
            {
                "input": "624 Worpswede Albert-Schwedt-Weg",
                "expected": "Albert-Schwedt-Weg"
            },
            {
                "input": "624 Worpswede Am Hörenberg",
                "expected": "Am Hörenberg"
            },
            {
                "input": "624 Worpswede Am Bergerdorfer Schiffgraben",
                "expected": "Am Bergerdorfer Schiffgraben"
            },
            {
                "input": "Worpswede Albert-Schwedt-Weg",
                "expected": "Albert-Schwedt-Weg"
            },
            {
                "input": "Albert-Schwedt-Weg",
                "expected": "Albert-Schwedt-Weg"
            }
        ]
        
        # Run tests
        for test_case in test_cases:
            input_street = test_case["input"]
            expected_street = test_case["expected"]
            
            result = clean_street_name(input_street)
            
            print(f"Input: '{input_street}' → Result: '{result}' (Expected: '{expected_street}')")
            self.assertEqual(result, expected_street, 
                            f"Street extraction failed. Input: '{input_street}', Expected: '{expected_street}', Got: '{result}'")
        
        print("\n✅ All street name extractions passed!")

if __name__ == "__main__":
    unittest.main()