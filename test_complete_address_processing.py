#!/usr/bin/env python3
import unittest
import re
import pandas as pd

class TestGermanAddressProcessing(unittest.TestCase):
    """Test the complete German address processing logic"""
    
    def test_complete_address_processing(self):
        """Test the complete address processing pipeline"""
        print("\n🔍 Testing complete German address processing pipeline...")
        
        # Define the street name extraction function
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
        
        # Define the house number extraction function
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
        
        # Create a test DataFrame with German addresses
        data = [
            {"Projektname Strasse": "624 Worpswede Albert-Schwedt-Weg", "Hausnummer": "5", "Zusatz": "", "PLZ": "27726", "Ort": "Worpswede"},
            {"Projektname Strasse": "624 Worpswede Albert-Schwedt-Weg", "Hausnummer": "1", "Zusatz": "", "PLZ": "27726", "Ort": "Worpswede"},
            {"Projektname Strasse": "624 Worpswede Albert-Schwedt-Weg", "Hausnummer": "3", "Zusatz": "", "PLZ": "27726", "Ort": "Worpswede"},
            {"Projektname Strasse": "624 Worpswede Albert-Schwedt-Weg", "Hausnummer": "12", "Zusatz": "", "PLZ": "27726", "Ort": "Worpswede"},
            {"Projektname Strasse": "624 Worpswede Albert-Schwedt-Weg", "Hausnummer": "2", "Zusatz": "", "PLZ": "27726", "Ort": "Worpswede"},
            {"Projektname Strasse": "624 Worpswede Am Hörenberg", "Hausnummer": "10", "Zusatz": "", "PLZ": "27726", "Ort": "Worpswede"},
            {"Projektname Strasse": "624 Worpswede Am Hörenberg", "Hausnummer": "1", "Zusatz": "A", "PLZ": "27726", "Ort": "Worpswede"},
            {"Projektname Strasse": "624 Worpswede Am Hörenberg", "Hausnummer": "3", "Zusatz": "A", "PLZ": "27726", "Ort": "Worpswede"},
            {"Projektname Strasse": "624 Worpswede Am Hörenberg", "Hausnummer": "8", "Zusatz": "", "PLZ": "27726", "Ort": "Worpswede"},
            {"Projektname Strasse": "624 Worpswede Am Hörenberg", "Hausnummer": "4", "Zusatz": "", "PLZ": "27726", "Ort": "Worpswede"},
            {"Projektname Strasse": "624 Worpswede Am Hörenberg", "Hausnummer": "3", "Zusatz": "C", "PLZ": "27726", "Ort": "Worpswede"},
            {"Projektname Strasse": "624 Worpswede Am Hörenberg", "Hausnummer": "7", "Zusatz": "", "PLZ": "27726", "Ort": "Worpswede"},
            {"Projektname Strasse": "624 Worpswede Am Bergerdorfer Schiffgraben", "Hausnummer": "50", "Zusatz": "", "PLZ": "27726", "Ort": "Worpswede"},
            {"Projektname Strasse": "624 Worpswede Am Bergerdorfer Schiffgraben", "Hausnummer": "30", "Zusatz": "", "PLZ": "27726", "Ort": "Worpswede"},
            {"Projektname Strasse": "624 Worpswede Am Bergerdorfer Schiffgraben", "Hausnummer": "64", "Zusatz": "", "PLZ": "27726", "Ort": "Worpswede"},
            {"Projektname Strasse": "624 Worpswede Am Bergerdorfer Schiffgraben", "Hausnummer": "34", "Zusatz": "", "PLZ": "27726", "Ort": "Worpswede"}
        ]
        
        df = pd.DataFrame(data)
        
        # Process the DataFrame
        # 1. Clean street names
        df['street_clean'] = df['Projektname Strasse'].apply(clean_street_name)
        
        # 2. Extract house number parts
        house_number_data = []
        for idx, row in df.iterrows():
            house_num = row['Hausnummer']
            zusatz = row['Zusatz']
            
            # Combine house number and zusatz for extraction
            house_num_str = f"{house_num}{zusatz}" if zusatz else house_num
            
            numeric, letter = extract_house_number_parts(house_num_str)
            house_number_data.append((numeric, letter))
        
        df['house_number_numeric'] = [data[0] for data in house_number_data]
        df['house_number_letter'] = [data[1] for data in house_number_data]
        
        # 3. Sort by street name and house number
        df_sorted = df.sort_values([
            'street_clean',           # PRIMARY: Group by street
            'house_number_numeric',   # SECONDARY: Numeric house number
            'house_number_letter'     # TERTIARY: Letter suffix
        ], na_position='last')
        
        # Print the sorted DataFrame
        print("\nSorted addresses:")
        for idx, row in df_sorted.iterrows():
            street = row['street_clean']
            house_num = row['Hausnummer']
            zusatz = row['Zusatz']
            house_display = f"{house_num}{zusatz}" if zusatz else house_num
            print(f"  - {street} {house_display}")
        
        # Group addresses by street
        street_groups = {}
        for idx, row in df_sorted.iterrows():
            street = row['street_clean']
            house_num = row['Hausnummer']
            zusatz = row['Zusatz']
            
            if street not in street_groups:
                street_groups[street] = []
            
            house_display = f"{house_num}{zusatz}" if zusatz else house_num
            street_groups[street].append(house_display)
        
        # Expected order for each street
        expected_orders = {
            "Albert-Schwedt-Weg": ["1", "2", "3", "5", "12"],
            "Am Hörenberg": ["1A", "3A", "3C", "4", "7", "8", "10"],
            "Am Bergerdorfer Schiffgraben": ["30", "34", "50", "64"]
        }
        
        # Verify that each street is correctly grouped and sorted
        print("\nVerifying street grouping and house number sorting:")
        for street, house_nums in street_groups.items():
            expected = expected_orders.get(street, [])
            print(f"\n{street}:")
            print(f"  Found: {house_nums}")
            print(f"  Expected: {expected}")
            
            self.assertEqual(house_nums, expected, 
                            f"House numbers for '{street}' are not in expected order. Found: {house_nums}, Expected: {expected}")
        
        print("\n✅ Complete German address processing test passed!")

if __name__ == "__main__":
    unittest.main()