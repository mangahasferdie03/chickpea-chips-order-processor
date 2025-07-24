import streamlit as st
import json
import re
import os
from typing import Dict, List, Optional
from dataclasses import dataclass
import anthropic
from dotenv import load_dotenv
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

# Load environment variables
load_dotenv()

# Configure page
st.set_page_config(
    page_title="Chickpea Chips Order Processor",
    page_icon="🥨",
    layout="wide"
)

@dataclass
class Product:
    code: str
    name: str
    size: str
    price: int = 290

@dataclass
class OrderItem:
    product: Product
    quantity: int

@dataclass
class ParsedOrder:
    customer_name: Optional[str]
    items: List[OrderItem]
    total_amount: int
    raw_message: str
    payment_method: Optional[str] = None
    customer_location: Optional[str] = None
    auto_sold_by: Optional[str] = None

# Product catalog
PRODUCTS = {
    "P-CHZ": Product("P-CHZ", "Cheese", "Pouch", 150),
    "P-SC": Product("P-SC", "Sour Cream", "Pouch", 150),
    "P-BBQ": Product("P-BBQ", "BBQ", "Pouch", 150),
    "P-OG": Product("P-OG", "Original", "Pouch", 150),
    "2L-CHZ": Product("2L-CHZ", "Cheese", "Tub", 290),
    "2L-SC": Product("2L-SC", "Sour Cream", "Tub", 290),
    "2L-BBQ": Product("2L-BBQ", "BBQ", "Tub", 290),
    "2L-OG": Product("2L-OG", "Original", "Tub", 290),
}

class OrderParser:
    def __init__(self, api_key: Optional[str] = None):
        # Try API key from parameter, then Streamlit secrets, then file, then environment variable
        if api_key:
            self.api_key = api_key
        else:
            # Try Streamlit secrets first (for cloud deployment)
            try:
                self.api_key = st.secrets["CLAUDE_API_KEY"]
            except:
                # Try to read from claude api.txt file (for local development)
                try:
                    with open('claude api.txt', 'r') as f:
                        self.api_key = f.read().strip()
                except:
                    # Fallback to environment variable
                    self.api_key = os.getenv('ANTHROPIC_API_KEY')
        
        if self.api_key:
            self.client = anthropic.Anthropic(api_key=self.api_key)
        else:
            self.client = None
    
    def _filipino_number_to_int(self, text: str) -> Dict[str, int]:
        """Convert Filipino number words to integers"""
        filipino_numbers = {
            'isa': 1, 'isang': 1, 'ung': 1,
            'dalawa': 2, 'dalawang': 2, 
            'tatlo': 3, 'tatlong': 3,
            'apat': 4, 'apatna': 4,
            'lima': 5, 'limang': 5,
            'anim': 6, 'anim na': 6,
            'pito': 7, 'pitong': 7,
            'walo': 8, 'walong': 8,
            'siyam': 9, 'siyamna': 9,
            'sampu': 10, 'sampung': 10
        }
        return filipino_numbers
    
    def _get_product_aliases(self) -> Dict[str, str]:
        """Map casual/Filipino product names to product codes"""
        return {
            # Cheese variations
            'cheese': ['P-CHZ', '2L-CHZ'],
            'cheesy': ['P-CHZ', '2L-CHZ'], 
            'cheese chips': ['P-CHZ'],
            'cheese tub': ['2L-CHZ'],
            'cheese pouch': ['P-CHZ'],
            'keso': ['P-CHZ', '2L-CHZ'],
            
            # Sour Cream variations
            'sour cream': ['P-SC', '2L-SC'],
            'sour': ['P-SC', '2L-SC'],
            'sc': ['P-SC', '2L-SC'],
            'sour cream chips': ['P-SC'],
            'sour cream tub': ['2L-SC'],
            'sour cream pouch': ['P-SC'],
            
            # BBQ variations
            'bbq': ['P-BBQ', '2L-BBQ'],
            'barbeque': ['P-BBQ', '2L-BBQ'],
            'barbecue': ['P-BBQ', '2L-BBQ'],
            'bbq chips': ['P-BBQ'],
            'bbq tub': ['2L-BBQ'],
            'bbq pouch': ['P-BBQ'],
            
            # Original variations
            'original': ['P-OG', '2L-OG'],
            'plain': ['P-OG', '2L-OG'],
            'orig': ['P-OG', '2L-OG'],
            'original chips': ['P-OG'],
            'original tub': ['2L-OG'],
            'original pouch': ['P-OG'],
            
            # Size indicators
            'pouch': 'pouch_size',
            'tub': 'tub_size',
            'malaki': 'tub_size',
            'maliit': 'pouch_size'
        }
    
    def parse_order_with_claude(self, message: str) -> ParsedOrder:
        """Parse order using enhanced Claude API with Filipino-English support"""
        if not self.client:
            return self._basic_parse(message)
        
        try:
            prompt = f"""
            You are an expert at parsing Filipino-English (Taglish) customer orders for chickpea chips from Facebook Messenger. 

            PRODUCTS AVAILABLE:
            - Pouches (₱150 each): Cheese (P-CHZ), Sour Cream (P-SC), BBQ (P-BBQ), Original (P-OG)
            - Tubs (₱290 each): Cheese (2L-CHZ), Sour Cream (2L-SC), BBQ (2L-BBQ), Original (2L-OG)

            FILIPINO NUMBER WORDS TO RECOGNIZE:
            - isa/isang = 1, dalawa/dalawang = 2, tatlo/tatlong = 3, apat = 4, lima/limang = 5
            - sampung = 10, etc.

            PRODUCT NAME VARIATIONS TO RECOGNIZE:
            - "cheese/cheesy/keso" = Cheese flavor
            - "sour cream/sour/sc" = Sour Cream flavor  
            - "bbq/barbeque/barbecue" = BBQ flavor
            - "original/plain/orig" = Original flavor
            - "pouch/maliit" = small size, "tub/malaki" = large size
            - Casual terms: "chips", "chickpea chips", etc.

            FILIPINO/CASUAL EXPRESSIONS TO HANDLE:
            - Politeness: "po", "please", "pwede", "pwede ba"
            - Requests: "gusto ko", "order ko", "bill ko"
            - For someone: "para kay [Name]", "para sa [Name]"
            - Quantities: "mga 2" (about 2), "mga tatlo" (about 3)

            PAYMENT METHODS TO DETECT:
            Look for these payment method keywords and map them to exact values:
            - "gcash", "g-cash", "GCash", "GCASH" → "Gcash"
            - "bpi", "BPI" → "BPI"  
            - "maya", "Maya", "MAYA", "paymaya" → "Maya"
            - "cash", "CASH", "cod", "cash on delivery", "bayad cash" → "Cash"
            - "bdo", "BDO" → "BDO"
            - Other payment methods → "Others"
            
            FILIPINO PAYMENT EXPRESSIONS:
            - "gcash ko", "sa gcash", "bayad gcash", "transfer gcash"
            - "maya payment", "bayad maya", "sa maya"
            - "cash po", "bayad cash", "cash on delivery"
            - "bpi transfer", "sa bpi", "bayad bpi"
            - "bdo naman", "sa bdo"

            LOCATION DETECTION FOR AUTOMATIC SELLER ASSIGNMENT:
            Look for location keywords to determine which seller handles the order:
            - "Quezon City", "QC", "quezon city", "qc" → "Quezon City"
            - "Paranaque", "Paranañaque", "paranaque", "parañaque" → "Paranaque"
            
            FILIPINO LOCATION EXPRESSIONS:
            - "sa QC", "galing QC", "dito sa Quezon City", "taga QC"
            - "sa Paranaque", "galing Paranaque", "dito sa Paranaque", "taga Paranaque"
            - "QC area", "Quezon City area", "Paranaque area"

            CRITICAL: HANDLE ORDER MODIFICATIONS AND REPLACEMENTS:
            Process modifications in CHRONOLOGICAL ORDER. Apply each change step-by-step.
            
            MODIFICATION KEYWORDS TO RECOGNIZE:
            - Additions: "add pa", "pa-add", "dagdag pa", "plus", "at saka", "pati", "kasama"
            - Removals: "tanggal", "patanggal", "remove", "wag na", "cancel", "hindi na"
            - Replacements: "replace", "pareplace", "palit", "change to", "instead of"
            - Complete changes: "hindi", "wait", "actually", "scratch that", "mas gusto ko"

            MANDATORY STEP-BY-STEP PROCESSING - FOLLOW EXACTLY:
            
            WHEN YOU SEE "patanggal" / "tanggal" / "remove":
            1. Identify EXACTLY what item and quantity to remove
            2. SUBTRACT that item from your current order list  
            3. Continue with remaining items only
            4. DO NOT include removed items in final result
            
            PROCESSING EXAMPLE - YOUR TEST CASE:
            "isang tub cheese po tapos padd na rin ng tatlong bbq pouch
            ay wait pwede patanggal yung tub cheese tapos pa-add na lang ng 3 sour cream tub
            tapos padd ng isa pang original blend na tub"
            
            MANDATORY STEP-BY-STEP:
            Step 1: Initial order = 1 cheese tub + 3 BBQ pouches
            Step 2: "patanggal yung tub cheese" = REMOVE 1 cheese tub 
                    Current order = 3 BBQ pouches (cheese tub DELETED)
            Step 3: "pa-add na lang ng 3 sour cream tub" = ADD 3 sour cream tubs
                    Current order = 3 BBQ pouches + 3 sour cream tubs  
            Step 4: "padd ng isa pang original blend na tub" = ADD 1 original tub
                    FINAL = 3 BBQ pouches + 3 sour cream tubs + 1 original tub = 7 items
            
            CRITICAL REMOVAL EXAMPLES:
            1. "2 cheese tub + 1 BBQ... patanggal yung cheese tub"
               → RESULT: 1 BBQ tub only (cheese REMOVED)
               
            2. "3 original pouch... tanggal ng dalawa... add BBQ tub"  
               → RESULT: 1 original pouch + 1 BBQ tub (2 original REMOVED)
               
            3. "cheese tub + sour tub... patanggal cheese... add 3 BBQ pouch"
               → RESULT: 1 sour tub + 3 BBQ pouches (cheese REMOVED)

            MANDATORY INSTRUCTIONS - NO EXCEPTIONS:
            1. Process modifications in EXACT chronological order
            2. When you see "patanggal"/"tanggal"/"remove": IMMEDIATELY delete that item from your running list
            3. When you see "pa-add"/"add"/"padd": ADD new items to your running list  
            4. When you see "pareplace"/"replace": DELETE old item FIRST, then ADD new item
            5. NEVER include removed items in your final JSON result
            6. Double-check: removed items should NOT appear in final order
            7. In "notes": List each step you processed: "Removed X, Added Y, etc."
            8. Verify final count: does it match your step-by-step calculation?
            
            ABSOLUTE RULE: If customer says "patanggal yung [item]" - that item MUST NOT be in final result.

            Return ONLY valid JSON with the FINAL corrected order:
            {{
                "customer_name": "extracted name or null",
                "payment_method": "Gcash" or "BPI" or "Maya" or "Cash" or "BDO" or "Others" or null,
                "customer_location": "Quezon City" or "Paranaque" or null,
                "items": [
                    {{"product_code": "P-CHZ", "quantity": 2}},
                    {{"product_code": "2L-BBQ", "quantity": 1}}
                ],
                "confidence": 0.95,
                "notes": "detected order modification/replacement" or "straightforward order"
            }}

            CUSTOMER MESSAGE TO PARSE:
            {message}
            """
            
            response = self.client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}]
            )
            
            return self._extract_and_validate_response(response, message)
                
        except Exception as e:
            st.error(f"Claude API error: {str(e)}")
            return self._basic_parse(message)
    
    def _extract_and_validate_response(self, response, original_message: str) -> ParsedOrder:
        """Extract and validate Claude's response with multiple fallback strategies"""
        try:
            response_text = response.content[0].text
            
            # Try to extract JSON with multiple strategies
            json_data = None
            
            # Strategy 1: Find JSON block
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                try:
                    json_data = json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass
            
            # Strategy 2: Find JSON between ```json blocks  
            if not json_data:
                json_match = re.search(r'```json\s*(\{.*?\})\s*```', response_text, re.DOTALL)
                if json_match:
                    try:
                        json_data = json.loads(json_match.group(1))
                    except json.JSONDecodeError:
                        pass
            
            # Strategy 3: Try parsing entire response as JSON
            if not json_data:
                try:
                    json_data = json.loads(response_text)
                except json.JSONDecodeError:
                    pass
            
            if json_data and 'items' in json_data:
                return self._create_order_from_json(json_data, original_message)
            else:
                # Fallback to basic parsing
                return self._basic_parse(original_message)
                
        except Exception as e:
            st.warning(f"Response parsing error: {str(e)}")
            return self._basic_parse(original_message)
    
    def _basic_parse(self, message: str) -> ParsedOrder:
        """Basic parsing without Claude API"""
        items = []
        
        # Simple pattern matching for product codes and quantities
        patterns = [
            r'(\d+)\s*x?\s*(P-CHZ|P-SC|P-BBQ|P-OG|2L-CHZ|2L-SC|2L-BBQ|2L-OG)',
            r'(P-CHZ|P-SC|P-BBQ|P-OG|2L-CHZ|2L-SC|2L-BBQ|2L-OG)\s*x?\s*(\d+)',
            r'(cheese|sour cream|bbq|original).*?(\d+)',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, message, re.IGNORECASE)
            for match in matches:
                if len(match) == 2:
                    if match[0].isdigit():
                        quantity, product_code = int(match[0]), match[1].upper()
                    elif match[1].isdigit():
                        product_code, quantity = match[0].upper(), int(match[1])
                    else:
                        continue
                    
                    if product_code in PRODUCTS:
                        items.append(OrderItem(PRODUCTS[product_code], quantity))
        
        # Extract customer name (basic attempt)
        name_patterns = [
            r'from\s+([A-Za-z\s]+)',
            r'([A-Za-z\s]+)\s+ordered',
            r'customer:\s*([A-Za-z\s]+)',
        ]
        
        customer_name = None
        for pattern in name_patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                customer_name = match.group(1).strip()
                break
        
        total = sum(item.quantity * item.product.price for item in items)
        
        # Basic payment method detection for fallback
        payment_method = self._detect_payment_method(message)
        
        # Basic location detection and seller assignment
        location, auto_sold_by = self._detect_location_and_seller(message)
        
        return ParsedOrder(customer_name, items, total, message, payment_method, location, auto_sold_by)
    
    def _detect_payment_method(self, message: str) -> Optional[str]:
        """Basic payment method detection for fallback when Claude API is not available"""
        message_lower = message.lower()
        
        # Check for payment method keywords
        if any(keyword in message_lower for keyword in ['gcash', 'g-cash', 'g cash']):
            return 'Gcash'
        elif any(keyword in message_lower for keyword in ['bpi']):
            return 'BPI'
        elif any(keyword in message_lower for keyword in ['maya', 'paymaya', 'pay maya']):
            return 'Maya'
        elif any(keyword in message_lower for keyword in ['cash', 'cod', 'cash on delivery', 'bayad cash']):
            return 'Cash'
        elif any(keyword in message_lower for keyword in ['bdo']):
            return 'BDO'
        elif any(keyword in message_lower for keyword in ['transfer', 'bank', 'online']):
            return 'Others'
        
        return None  # No payment method detected
    
    def _detect_location_and_seller(self, message: str) -> tuple[Optional[str], Optional[str]]:
        """Detect customer location and automatically assign seller"""
        message_lower = message.lower()
        
        # Check for Quezon City / QC keywords
        qc_keywords = ['quezon city', 'qc', 'sa qc', 'galing qc', 'dito sa quezon city', 'taga qc', 'qc area']
        if any(keyword in message_lower for keyword in qc_keywords):
            return 'Quezon City', 'Ferdie'
        
        # Check for Paranaque keywords  
        paranaque_keywords = ['paranaque', 'paranañaque', 'parañaque', 'sa paranaque', 'galing paranaque', 
                             'dito sa paranaque', 'taga paranaque', 'paranaque area']
        if any(keyword in message_lower for keyword in paranaque_keywords):
            return 'Paranaque', 'Nina'
        
        return None, None  # No location detected
    
    def _create_order_from_json(self, data: dict, raw_message: str) -> ParsedOrder:
        """Create ParsedOrder from JSON data with enhanced information"""
        items = []
        for item_data in data.get('items', []):
            product_code = item_data.get('product_code', '').upper()
            quantity = item_data.get('quantity', 0)
            
            if product_code in PRODUCTS and quantity > 0:
                items.append(OrderItem(PRODUCTS[product_code], quantity))
        
        total = sum(item.quantity * item.product.price for item in items)
        
        # Get location from Claude response and determine seller
        location = data.get('customer_location')
        auto_sold_by = None
        if location == 'Quezon City':
            auto_sold_by = 'Ferdie'
        elif location == 'Paranaque':
            auto_sold_by = 'Nina'
        
        # Create enhanced ParsedOrder with additional Claude data
        order = ParsedOrder(
            customer_name=data.get('customer_name'),
            items=items,
            total_amount=total,
            raw_message=raw_message,
            payment_method=data.get('payment_method'),
            customer_location=location,
            auto_sold_by=auto_sold_by
        )
        
        # Add Claude-specific metadata
        if hasattr(order, '__dict__'):
            order.confidence = data.get('confidence', 0.0)
            order.parsing_notes = data.get('notes', '')
        
        return order

class GoogleSheetsIntegration:
    def __init__(self, credentials_path: str = "google_credentials.json"):
        """Initialize Google Sheets integration with service account credentials"""
        self.credentials_path = credentials_path
        self.gc = None
        self.spreadsheet = None
        self.worksheet = None
        
    def connect(self, spreadsheet_id: str, worksheet_name: str = "ORDER") -> bool:
        """Connect to Google Sheets API and open the specified spreadsheet"""
        try:
            # Try to load credentials from multiple sources
            creds_data = None
            
            # First try Streamlit secrets (for cloud deployment)
            try:
                creds_data = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
            except:
                # Fallback to local file (for development)
                try:
                    if os.path.exists(self.credentials_path):
                        with open(self.credentials_path, 'r') as f:
                            creds_data = json.load(f)
                    else:
                        raise FileNotFoundError(f"Credentials file not found: {self.credentials_path}")
                except Exception as file_error:
                    raise Exception(f"Could not load Google credentials from file or secrets: {file_error}")
            
            if not creds_data:
                raise Exception("No Google credentials found in secrets or file")
            
            # Set up credentials with required scopes
            scopes = [
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive'
            ]
            
            credentials = Credentials.from_service_account_info(creds_data, scopes=scopes)
            self.gc = gspread.authorize(credentials)
            
            # Open the spreadsheet and worksheet
            self.spreadsheet = self.gc.open_by_key(spreadsheet_id)
            self.worksheet = self.spreadsheet.worksheet(worksheet_name)
            
            return True
            
        except Exception as e:
            st.error(f"Failed to connect to Google Sheets: {str(e)}")
            return False
    
    def find_next_available_row(self) -> int:
        """Find the next available row by checking both customer name (D) and product columns (N,O,P,Q,T,U,V,W)"""
        try:
            # Get all data for the relevant columns at once
            # Column D = Customer Name, Columns N,O,P,Q,T,U,V,W = Product quantities
            relevant_columns = ['D', 'N', 'O', 'P', 'Q', 'T', 'U', 'V', 'W']
            
            # Get data from all relevant columns (we'll check up to row 2000 to be safe)
            range_to_check = "D1:W2000"
            all_data = self.worksheet.get(range_to_check)
            
            last_row_with_data = 1  # Start from row 1 (headers)
            
            # Check each row for data in relevant columns
            for row_index, row_data in enumerate(all_data):
                actual_row_number = row_index + 1  # Convert to 1-based row number
                
                if actual_row_number == 1:  # Skip header row
                    continue
                
                # Check if this row has data in customer name (column D = index 0 in our range)
                has_customer_data = False
                if len(row_data) > 0 and row_data[0] and str(row_data[0]).strip():
                    has_customer_data = True
                
                # Check if this row has data in any product columns (N,O,P,Q,T,U,V,W)
                # In our range D1:W2000, columns N,O,P,Q,T,U,V,W are at indices 10,11,12,13,16,17,18,19
                product_column_indices = [10, 11, 12, 13, 16, 17, 18, 19]  # N,O,P,Q,T,U,V,W
                has_product_data = False
                
                for col_index in product_column_indices:
                    if (len(row_data) > col_index and 
                        row_data[col_index] and 
                        str(row_data[col_index]).strip() and
                        str(row_data[col_index]).strip() != '0'):
                        has_product_data = True
                        break
                
                # If either customer data OR product data exists, this row is occupied
                if has_customer_data or has_product_data:
                    last_row_with_data = actual_row_number
            
            # Return the next available row
            next_available = last_row_with_data + 1
            
            return next_available
                
        except Exception as e:
            st.warning(f"Could not auto-detect next row: {str(e)}")
            return 526  # Fallback to expected row
    
    def update_order_row(self, parsed_order: ParsedOrder, row_number: int, sold_by: str = "") -> bool:
        """Update a specific row with order data with comprehensive logging"""
        try:
            st.info(f"🔄 Starting update_order_row for row {row_number}")
            today = datetime.now()
            
            # Log connection status
            if not self.worksheet:
                st.error("❌ No worksheet connection available")
                return False
                
            st.success(f"✅ Worksheet connection confirmed: {self.worksheet.title}")
            
            # Create a dictionary for easier column mapping
            update_data = {}
            
            # Column C: Order Date
            update_data['C'] = today.strftime("%Y-%m-%d")
            
            # Column D: Customer Name
            update_data['D'] = parsed_order.customer_name or "Unknown"
            
            # Column E: Sold By
            update_data['E'] = sold_by
            
            # Column H: Payment Status
            update_data['H'] = "Unpaid"
            
            # Product quantities
            st.info(f"📦 Processing {len(parsed_order.items)} products...")
            for item in parsed_order.items:
                product_code = item.product.code
                quantity = item.quantity
                st.info(f"  - {product_code}: {quantity}")
                
                # Map product codes to columns
                if product_code == "P-CHZ":      # Column N
                    update_data['N'] = quantity
                elif product_code == "P-SC":     # Column O
                    update_data['O'] = quantity
                elif product_code == "P-BBQ":    # Column P
                    update_data['P'] = quantity
                elif product_code == "P-OG":     # Column Q
                    update_data['Q'] = quantity
                elif product_code == "2L-CHZ":   # Column T
                    update_data['T'] = quantity
                elif product_code == "2L-SC":    # Column U
                    update_data['U'] = quantity
                elif product_code == "2L-BBQ":   # Column V
                    update_data['V'] = quantity
                elif product_code == "2L-OG":    # Column W
                    update_data['W'] = quantity
            
            # Show prepared data
            st.info(f"📋 Prepared {len(update_data)} updates:")
            st.json(update_data)
            
            # Update using individual cell updates with detailed logging
            st.info("🔧 Starting individual cell updates...")
            updates_made = []
            failed_updates = []
            
            for column_letter, value in update_data.items():
                if value:  # Only update non-empty values
                    # Convert column letter to number (A=1, B=2, etc.)
                    col_num = ord(column_letter) - ord('A') + 1
                    
                    st.info(f"  📝 Updating {column_letter}{row_number} (row {row_number}, col {col_num}) = '{value}'")
                    
                    try:
                        # Perform the update
                        result = self.worksheet.update_cell(row_number, col_num, value)
                        st.success(f"  ✅ {column_letter}{row_number}: '{value}' -> Success")
                        updates_made.append(f"{column_letter}{row_number}: {value}")
                        
                        # Log API response if available
                        if hasattr(result, 'get'):
                            st.info(f"    API Response: {result}")
                            
                    except Exception as cell_error:
                        error_msg = f"Failed to update {column_letter}{row_number}: {cell_error}"
                        st.error(f"  ❌ {error_msg}")
                        failed_updates.append(error_msg)
            
            # Summary
            if updates_made:
                st.success(f"✅ Successfully updated {len(updates_made)} cells:")
                for update in updates_made:
                    st.text(f"  • {update}")
            
            if failed_updates:
                st.error(f"❌ Failed to update {len(failed_updates)} cells:")
                for failure in failed_updates:
                    st.text(f"  • {failure}")
            
            final_result = len(updates_made) > 0
            st.info(f"🏁 Final result: {final_result} ({len(updates_made)} successful, {len(failed_updates)} failed)")
            
            return final_result
            
        except Exception as e:
            st.error(f"❌ Major error in update_order_row: {str(e)}")
            import traceback
            st.code(traceback.format_exc())
            return False
    
    def update_order_row_batch(self, parsed_order: ParsedOrder, row_number: int, sold_by: str = "") -> bool:
        """Alternative batch update method"""
        try:
            st.info(f"🔄 Starting batch update for row {row_number}")
            today = datetime.now()
            
            # Prepare row data (28 columns to match sheet structure)
            row_data = [""] * 28
            
            # Fill in the data at correct indices
            row_data[2] = today.strftime("%Y-%m-%d")      # Column C
            row_data[3] = parsed_order.customer_name or "Unknown"  # Column D
            row_data[4] = sold_by                         # Column E
            row_data[7] = "Unpaid"                        # Column H
            
            # Product quantities
            for item in parsed_order.items:
                product_code = item.product.code
                quantity = item.quantity
                
                if product_code == "P-CHZ":      # Column N (index 13)
                    row_data[13] = quantity
                elif product_code == "P-SC":     # Column O (index 14)
                    row_data[14] = quantity
                elif product_code == "P-BBQ":    # Column P (index 15)
                    row_data[15] = quantity
                elif product_code == "P-OG":     # Column Q (index 16)
                    row_data[16] = quantity
                elif product_code == "2L-CHZ":   # Column T (index 19)
                    row_data[19] = quantity
                elif product_code == "2L-SC":    # Column U (index 20)
                    row_data[20] = quantity
                elif product_code == "2L-BBQ":   # Column V (index 21)
                    row_data[21] = quantity
                elif product_code == "2L-OG":    # Column W (index 22)
                    row_data[22] = quantity
            
            # Show what we're sending
            st.info("📦 Batch update data (non-empty values):")
            batch_preview = {}
            for i, value in enumerate(row_data):
                if value:
                    column_letter = chr(65 + i)
                    batch_preview[f"Column {column_letter}"] = value
            st.json(batch_preview)
            
            # Perform batch update
            range_name = f"A{row_number}:AB{row_number}"  # 28 columns
            st.info(f"📍 Updating range: {range_name}")
            
            # Log pre-update state
            st.info("🔍 API CALL DETAILS:")
            st.info(f"  - Worksheet title: {self.worksheet.title}")
            st.info(f"  - Worksheet ID: {self.worksheet.id}")
            st.info(f"  - Range: {range_name}")
            st.info(f"  - Data length: {len(row_data)}")
            st.info(f"  - Non-empty values: {sum(1 for x in row_data if x)}")
            
            try:
                result = self.worksheet.update(
                    values=[row_data],
                    range_name=range_name
                )
                
                # Deep dive into API response
                st.success("✅ API call completed")
                st.info("🔍 COMPLETE API RESPONSE:")
                st.json({
                    "result_type": str(type(result)),
                    "result_content": str(result),
                    "has_updated_rows": hasattr(result, 'get') and 'updatedRows' in str(result),
                    "has_updated_cells": hasattr(result, 'get') and 'updatedCells' in str(result),
                })
                
                # Try to extract specific response fields
                if hasattr(result, 'get'):
                    try:
                        response_details = {
                            "updated_rows": result.get('updatedRows', 'NOT_FOUND'),
                            "updated_columns": result.get('updatedColumns', 'NOT_FOUND'),
                            "updated_cells": result.get('updatedCells', 'NOT_FOUND'),
                            "updated_range": result.get('updatedRange', 'NOT_FOUND'),
                        }
                        st.info("📊 Response Details:")
                        st.json(response_details)
                    except Exception as extract_error:
                        st.warning(f"Could not extract response details: {extract_error}")
                
                # Check if the result indicates success
                result_indicates_success = bool(result)
                st.info(f"🎯 Result indicates success: {result_indicates_success}")
                
                return result_indicates_success
                
            except Exception as api_error:
                st.error(f"❌ API call failed: {api_error}")
                st.error(f"Error type: {type(api_error)}")
                import traceback
                st.code(traceback.format_exc())
                return False
            
        except Exception as e:
            st.error(f"❌ Batch update failed: {str(e)}")
            import traceback
            st.code(traceback.format_exc())
            return False
    
    def update_order_simple(self, parsed_order: ParsedOrder, row_number: int, sold_by: str = "") -> bool:
        """Clean, simple update method that only updates specific columns"""
        try:
            today = datetime.now()
            
            # Update only specific cells instead of entire row to avoid overwriting formulas
            updates = {}
            
            # Basic order info - only update these specific columns
            updates['C'] = today.strftime("%Y-%m-%d")                    # Column C: Date
            updates['D'] = parsed_order.customer_name or "Unknown"       # Column D: Customer
            
            # Sold By - only update if location was detected and seller assigned
            if parsed_order.auto_sold_by:
                updates['E'] = parsed_order.auto_sold_by                 # Column E: Auto-assigned Sold By
            
            updates['H'] = "Unpaid"                                      # Column H: Payment Status
            
            # Payment method - only update Column G if payment method was detected
            if parsed_order.payment_method:
                updates['G'] = parsed_order.payment_method               # Column G: Payment Method
            
            # Fun note - add robot emoji to indicate web app processing
            updates['J'] = "🤖"                                          # Column J: Notes (robot emoji)
            
            # Order type - always set to Reserved for all web orders
            updates['K'] = "Reserved"                                    # Column K: Note (always Reserved)
            
            # Product quantities - only update product columns
            for item in parsed_order.items:
                product_code = item.product.code
                quantity = item.quantity
                
                if product_code == "P-CHZ":      # Column N
                    updates['N'] = quantity
                elif product_code == "P-SC":     # Column O
                    updates['O'] = quantity
                elif product_code == "P-BBQ":    # Column P
                    updates['P'] = quantity
                elif product_code == "P-OG":     # Column Q
                    updates['Q'] = quantity
                elif product_code == "2L-CHZ":   # Column T
                    updates['T'] = quantity
                elif product_code == "2L-SC":    # Column U
                    updates['U'] = quantity
                elif product_code == "2L-BBQ":   # Column V
                    updates['V'] = quantity
                elif product_code == "2L-OG":    # Column W
                    updates['W'] = quantity
            
            # Update cells individually to avoid overwriting formulas
            for column_letter, value in updates.items():
                if value:  # Only update non-empty values
                    cell_address = f"{column_letter}{row_number}"
                    col_num = ord(column_letter) - ord('A') + 1
                    self.worksheet.update_cell(row_number, col_num, value)
            
            return True
            
        except Exception as e:
            st.error(f"Update failed: {str(e)}")
            return False


def main():
    st.title("🥨 Chickpea Chips Order Processor")
    st.markdown("### Automated Facebook Messenger Order Processing")
    
    # Sidebar for API configuration
    with st.sidebar:
        st.header("⚙️ Configuration")
        
        # Check API key status (multiple sources)
        secrets_key = None
        file_key = None
        env_key = os.getenv('ANTHROPIC_API_KEY')
        
        # Check Streamlit secrets
        try:
            secrets_key = st.secrets["CLAUDE_API_KEY"]
        except:
            pass
        
        # Check file (for local development)
        try:
            with open('claude api.txt', 'r') as f:
                file_key = f.read().strip()
        except:
            pass
        
        if secrets_key:
            st.success("✅ Claude API Key from Streamlit secrets - Enhanced parsing enabled")
        elif file_key:
            st.success("✅ Claude API Key from file - Enhanced parsing enabled")
        elif env_key:
            st.success("✅ API Key from environment - Enhanced parsing enabled")
        else:
            st.warning("⚠️ No API Key found - Using basic parsing only")
        
        st.divider()
        
        # Google Sheets Configuration
        st.header("📊 Google Sheets Integration")
        spreadsheet_id = st.text_input(
            "Google Sheets ID", 
            value="1DGt5u6QWWIMRZmU1MzfM3sowFPt9lOJPAgjqxZ6uGtc",
            help="The ID from your Google Sheets URL"
        )
        
        
        # Row override option (simplified)
        use_custom_row = st.checkbox("Override row number")
        if use_custom_row:
            custom_row = st.number_input(
                "Custom Row Number",
                min_value=2,
                max_value=2000,
                value=526,
                help="Specify exact row number to use"
            )
            st.session_state.custom_row = custom_row
        else:
            # Remove custom row from session state if not using override
            if 'custom_row' in st.session_state:
                del st.session_state.custom_row
        
    
    # Main interface
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.header("📝 Customer Message")
        
        # Show example messages
        with st.expander("💡 See Filipino-English Example Messages"):
            st.markdown("""
            **English Examples:**
            - "Hi! I'd like to order 2 cheese pouches and 1 BBQ tub please. This is for Maria Santos."
            - "Can I get 3 sour cream chips and 2 original tubs?"
            
            **Filipino-English (Taglish) Examples:**
            - "pwede bang dalawang cheese tub at isang sour cream pouch po"
            - "hey gusto ko tatlong BBQ please, yung malaki ha para kay Maria"  
            - "isa lang cheese chips tsaka 2 original tub"
            - "mga 3 keso please, yung maliit lang, order ni Juan"
            - "dalawang malaki BBQ tsaka isang maliit cheese po"
            
            **Order Modifications/Corrections (Fixed!):**
            - "gusto ko 2 cheese tub... wait hindi, make it 3 BBQ pouch na lang po"
            - "pwede bang 3 sour cream tub... actually scratch that, 2 original pouch para kay Maria"
            - "isa cheese tub tsaka dalawang BBQ... ay hindi pala, palit ko ng tatlong cheese pouch"
            - "5 original tub please... wait wag na, mas gusto ko 2 cheese tub at 1 sour cream pouch"
            - "dalawang BBQ pouch... dagdag pa ng isang cheese tub" (addition, not replacement)
            """)
        
        message_input = st.text_area(
            "Paste Facebook Messenger conversation:",
            height=300,
            placeholder="Paste the customer's message here...\n\nEnglish: Hi! I'd like 2 cheese pouches and 1 BBQ tub please. For Maria Santos.\n\nTaglish: pwede bang dalawang cheese tub at isang sour cream pouch po para kay Juan"
        )
        
        process_button = st.button("🔄 Process Order", type="primary", use_container_width=True)
    
    with col2:
        st.header("📊 Parsed Order Results")
        
        if process_button and message_input.strip():
            with st.spinner("Processing order..."):
                # Silently get fresh row number from Google Sheets
                if spreadsheet_id:
                    try:
                        sheets = GoogleSheetsIntegration()
                        if sheets.connect(spreadsheet_id, "ORDER"):
                            # Check if user wants to override row number
                            if 'custom_row' in st.session_state:
                                next_row = st.session_state.custom_row
                            else:
                                next_row = sheets.find_next_available_row()
                            
                            # Store the detected row for the update button
                            st.session_state.next_row = next_row
                        else:
                            st.session_state.next_row = 526
                    except Exception as e:
                        st.session_state.next_row = 526
                else:
                    st.session_state.next_row = 526
                
                # Parse the order silently
                parser = OrderParser()  # API key auto-loaded from file
                parsed_order = parser.parse_order_with_claude(message_input)
                
                # Store in session state so it persists across button clicks
                st.session_state.parsed_order = parsed_order
                
        # Check if we have a parsed order (either just processed or from session state)
        if hasattr(st.session_state, 'parsed_order') and st.session_state.parsed_order:
            parsed_order = st.session_state.parsed_order
            
            if parsed_order.items:
                # Display customer info
                if parsed_order.customer_name:
                    st.success(f"**Customer:** {parsed_order.customer_name}")
                else:
                    st.warning("**Customer:** Name not detected")
                
                # Display payment method
                if parsed_order.payment_method:
                    st.success(f"**Payment Method:** {parsed_order.payment_method}")
                else:
                    st.info("**Payment Method:** Not specified")
                
                # Display location and assigned seller
                if parsed_order.customer_location and parsed_order.auto_sold_by:
                    st.success(f"**Location:** {parsed_order.customer_location}")
                    st.success(f"**Assigned to:** {parsed_order.auto_sold_by}")
                else:
                    st.info("**Location:** Not specified")
                    st.info("**Assigned to:** Not assigned")
                
                # Display order items
                st.subheader("📋 Order Items")
                total_items = 0
                for item in parsed_order.items:
                    total_item_price = item.quantity * item.product.price
                    st.text(f"{item.product.name} {item.product.size} - {item.quantity} - ₱{total_item_price:,}")
                    total_items += item.quantity
                
                st.text("----------")
                st.text(f"Total - ₱{parsed_order.total_amount:,}")
                
                # Export data
                order_data = {
                    "customer_name": parsed_order.customer_name,
                    "payment_method": parsed_order.payment_method,
                    "customer_location": parsed_order.customer_location,
                    "auto_sold_by": parsed_order.auto_sold_by,
                    "items": [
                        {
                            "product_code": item.product.code,
                            "product_name": f"{item.product.name} {item.product.size}",
                            "quantity": item.quantity,
                            "unit_price": item.product.price,
                            "total_price": item.quantity * item.product.price
                        }
                        for item in parsed_order.items
                    ],
                    "total_amount": parsed_order.total_amount,
                    "total_items": total_items
                }
                
                st.download_button(
                    "📥 Download Order JSON",
                    data=json.dumps(order_data, indent=2),
                    file_name="order.json",
                    mime="application/json"
                )
                
                # Google Sheets Integration
                st.divider()
                st.subheader("📊 Google Sheets Integration")
                    
                if spreadsheet_id:  # Only need spreadsheet ID
                    # Get the row number that was detected during order processing
                    target_row = st.session_state.get('next_row', 526)
                    
                    # Show what will be added to Google Sheets
                    with st.expander("🔍 Preview Order Data"):
                        preview_data = {
                            "Row": target_row,
                            "Order Date": datetime.now().strftime('%Y-%m-%d'),
                            "Customer Name": parsed_order.customer_name or 'Unknown',
                            "Sold By": parsed_order.auto_sold_by or "Not assigned",
                            "Payment Method": parsed_order.payment_method or "Not specified",
                            "Payment Status": "Unpaid",
                            "Products": []
                        }
                        
                        for item in parsed_order.items:
                            preview_data["Products"].append({
                                "Code": item.product.code,
                                "Name": f"{item.product.name} {item.product.size}",
                                "Quantity": item.quantity
                            })
                        
                        st.json(preview_data)
                    
                    # REBUILT Update Google Sheet button - Clean & Simple
                    if st.button("📊 Update Google Sheet", type="primary", use_container_width=True):
                        with st.spinner("Updating Google Sheet..."):
                            try:
                                # Simple connection
                                sheets = GoogleSheetsIntegration()
                                if not sheets.connect(spreadsheet_id, "ORDER"):
                                    st.error("❌ Could not connect to Google Sheets")
                                    st.stop()
                                
                                # Use the freshly detected row number from order processing
                                success = sheets.update_order_simple(parsed_order, target_row)
                                
                                if success:
                                    st.success(f"✅ Successfully updated row {target_row}!")
                                    st.balloons()
                                    st.info(f"💡 Order added to row {target_row}")
                                    
                                else:
                                    st.error("❌ Update failed - please try again")
                                    
                            except Exception as e:
                                st.error(f"❌ Error: {str(e)}")
                                st.info("💡 Please check your connection and try again")
                else:
                    st.warning("⚠️ Please enter your Google Sheets ID in the sidebar")
            else:
                st.error("❌ No valid products found in the message. Please check the format.")
        
        elif process_button:
            st.warning("⚠️ Please enter a customer message to process.")
        else:
            st.info("👆 Enter a customer message and click 'Process Order' to get started.")

if __name__ == "__main__":
    main()
