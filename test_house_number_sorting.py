#!/usr/bin/env python3
import unittest
import re

class TestHouseNumberSorting(unittest.TestCase):
    """Test the house number sorting logic directly"""
    
    def test_extract_house_number_parts(self):
        """Test the extract_house_number_parts function logic"""
        print("\n🔍 Testing house number extraction function...")
        
        # This is a simplified version of the extract_house_number_parts function from server.py
        def extract_house_number_parts(house_number_str):
            """Extract numeric and alphabetic parts from house number for proper sorting"""
            # Handle NaN, None, empty strings, etc.
            if house_number_str is None or house_number_str == '' or str(house_number_str).strip() == '' or str(house_number_str).strip().lower() == 'nan':
                return 0, ''
            
            # Convert to string and strip whitespace
            house_str = str(house_number_str).strip()
            
            # Use regex to extract number and letter parts
            match = re.match(r'^(\d+)([A-Za-z]*).*', house_str)
            if match:
                try:
                    number = int(match.group(1))
                    letter = match.group(2).upper() if match.group(2) else ''
                    return number, letter
                except ValueError:
                    return 0, house_str
            else:
                # If no number found, try to extract any number
                numbers = re.findall(r'\d+', house_str)
                if numbers:
                    try:
                        return int(numbers[0]), ''
                    except ValueError:
                        return 0, house_str
                else:
                    return 0, house_str
        
        # Test cases
        test_cases = [
            {"input": "1", "expected_num": 1, "expected_letter": ""},
            {"input": "10", "expected_num": 10, "expected_letter": ""},
            {"input": "1A", "expected_num": 1, "expected_letter": "A"},
            {"input": "3C", "expected_num": 3, "expected_letter": "C"},
            {"input": "12B", "expected_num": 12, "expected_letter": "B"},
            {"input": "10a", "expected_num": 10, "expected_letter": "A"},  # Should uppercase the letter
            {"input": "5 A", "expected_num": 5, "expected_letter": ""},    # Space should break the pattern
            {"input": "", "expected_num": 0, "expected_letter": ""},       # Empty string
            {"input": None, "expected_num": 0, "expected_letter": ""},     # None value
            {"input": "nan", "expected_num": 0, "expected_letter": ""},    # NaN string
            {"input": "House 5", "expected_num": 5, "expected_letter": ""} # Number extraction from text
        ]
        
        # Run tests
        for test_case in test_cases:
            input_house_num = test_case["input"]
            expected_num = test_case["expected_num"]
            expected_letter = test_case["expected_letter"]
            
            num, letter = extract_house_number_parts(input_house_num)
            
            print(f"Input: '{input_house_num}' → Result: ({num}, '{letter}') (Expected: ({expected_num}, '{expected_letter}'))")
            self.assertEqual(num, expected_num, 
                            f"House number extraction failed. Input: '{input_house_num}', Expected num: {expected_num}, Got: {num}")
            self.assertEqual(letter, expected_letter, 
                            f"House number letter extraction failed. Input: '{input_house_num}', Expected letter: '{expected_letter}', Got: '{letter}'")
        
        print("\n✅ All house number extractions passed!")
    
    def test_house_number_sorting(self):
        """Test the house number sorting logic"""
        print("\n🔍 Testing house number sorting logic...")
        
        # This is a simplified version of the extract_house_number_parts function from server.py
        def extract_house_number_parts(house_number_str):
            """Extract numeric and alphabetic parts from house number for proper sorting"""
            # Handle NaN, None, empty strings, etc.
            if house_number_str is None or house_number_str == '' or str(house_number_str).strip() == '' or str(house_number_str).strip().lower() == 'nan':
                return 0, ''
            
            # Convert to string and strip whitespace
            house_str = str(house_number_str).strip()
            
            # Use regex to extract number and letter parts
            match = re.match(r'^(\d+)([A-Za-z]*).*', house_str)
            if match:
                try:
                    number = int(match.group(1))
                    letter = match.group(2).upper() if match.group(2) else ''
                    return number, letter
                except ValueError:
                    return 0, house_str
            else:
                # If no number found, try to extract any number
                numbers = re.findall(r'\d+', house_str)
                if numbers:
                    try:
                        return int(numbers[0]), ''
                    except ValueError:
                        return 0, house_str
                else:
                    return 0, house_str
        
        # Test data - addresses with house numbers in random order
        addresses = [
            {"street": "Am Hörenberg", "house_num": "10"},
            {"street": "Am Hörenberg", "house_num": "1", "zusatz": "A"},
            {"street": "Am Hörenberg", "house_num": "3", "zusatz": "A"},
            {"street": "Am Hörenberg", "house_num": "8"},
            {"street": "Am Hörenberg", "house_num": "4"},
            {"street": "Am Hörenberg", "house_num": "3", "zusatz": "C"},
            {"street": "Am Hörenberg", "house_num": "7"},
            {"street": "Albert-Schwedt-Weg", "house_num": "5"},
            {"street": "Albert-Schwedt-Weg", "house_num": "1"},
            {"street": "Albert-Schwedt-Weg", "house_num": "3"},
            {"street": "Albert-Schwedt-Weg", "house_num": "12"},
            {"street": "Albert-Schwedt-Weg", "house_num": "2"},
            {"street": "Am Bergerdorfer Schiffgraben", "house_num": "50"},
            {"street": "Am Bergerdorfer Schiffgraben", "house_num": "30"},
            {"street": "Am Bergerdorfer Schiffgraben", "house_num": "64"},
            {"street": "Am Bergerdorfer Schiffgraben", "house_num": "34"}
        ]
        
        # Add sorting keys to each address
        for addr in addresses:
            house_num = addr.get("house_num", "")
            zusatz = addr.get("zusatz", "")
            
            num, letter = extract_house_number_parts(f"{house_num}{zusatz}")
            addr["sort_num"] = num
            addr["sort_letter"] = letter
        
        # Group addresses by street
        street_groups = {}
        for addr in addresses:
            street = addr["street"]
            if street not in street_groups:
                street_groups[street] = []
            street_groups[street].append(addr)
        
        # Sort each street group by house number
        for street, addrs in street_groups.items():
            sorted_addrs = sorted(addrs, key=lambda x: (x["sort_num"], x["sort_letter"]))
            
            # Print the sorted addresses
            print(f"\n{street} - sorted house numbers:")
            house_nums = []
            for addr in sorted_addrs:
                house_num = addr.get("house_num", "")
                zusatz = addr.get("zusatz", "")
                display = f"{house_num}{zusatz}" if zusatz else house_num
                house_nums.append(display)
                print(f"  - {display}")
            
            # Expected order for each street
            expected_orders = {
                "Am Hörenberg": ["1A", "3A", "3C", "4", "7", "8", "10"],
                "Albert-Schwedt-Weg": ["1", "2", "3", "5", "12"],
                "Am Bergerdorfer Schiffgraben": ["30", "34", "50", "64"]
            }
            
            # Check if house numbers match expected order
            expected = expected_orders.get(street, [])
            print(f"  Found: {house_nums}")
            print(f"  Expected: {expected}")
            
            self.assertEqual(house_nums, expected, 
                            f"House numbers for '{street}' are not in expected order. Found: {house_nums}, Expected: {expected}")
        
        print("\n✅ All house number sorting tests passed!")

if __name__ == "__main__":
    unittest.main()