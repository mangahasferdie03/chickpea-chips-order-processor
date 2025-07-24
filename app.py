import os
import re
import json
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass

import streamlit as st
import anthropic
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

# --- Load environment variables once ---
load_dotenv()

# --- Page Config ---
st.set_page_config(page_title="Chickpea Chips Order Processor", page_icon="🍟", layout="wide")


# -----------------------------
# Data Models
# -----------------------------
@dataclass
class Product:
    code: str
    name: str
    size: str
    price: int


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


# -----------------------------
# Constants & Cached Data
# -----------------------------
@st.cache_data
def get_products() -> Dict[str, Product]:
    return {
        "P-CHZ": Product("P-CHZ", "Cheese", "Pouch", 150),
        "P-SC": Product("P-SC", "Sour Cream", "Pouch", 150),
        "P-BBQ": Product("P-BBQ", "BBQ", "Pouch", 150),
        "P-OG": Product("P-OG", "Original", "Pouch", 150),
        "2L-CHZ": Product("2L-CHZ", "Cheese", "Tub", 290),
        "2L-SC": Product("2L-SC", "Sour Cream", "Tub", 290),
        "2L-BBQ": Product("2L-BBQ", "BBQ", "Tub", 290),
        "2L-OG": Product("2L-OG", "Original", "Tub", 290),
    }


PRODUCT_COLUMN_MAP = {
    "P-CHZ": "N", "P-SC": "O", "P-BBQ": "P", "P-OG": "Q",
    "2L-CHZ": "T", "2L-SC": "U", "2L-BBQ": "V", "2L-OG": "W"
}


@st.cache_data
def load_api_key() -> Optional[str]:
    try:
        return st.secrets.get("CLAUDE_API_KEY") or os.getenv('ANTHROPIC_API_KEY') \
               or open('claude api.txt').read().strip()
    except FileNotFoundError:
        return None


# -----------------------------
# Order Parser
# -----------------------------
class OrderParser:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or load_api_key()
        self.client = anthropic.Anthropic(api_key=self.api_key) if self.api_key else None
        self._product_pattern = re.compile(r'(\d+)\s*x?\s*([A-Za-z0-9-]+)', re.I)

    def parse(self, message: str) -> ParsedOrder:
        if self.client:
            try:
                return self._parse_with_claude(message)
            except Exception:
                pass
        return self._basic_parse(message)

    def _parse_with_claude(self, message: str) -> ParsedOrder:
        prompt = CLAUDE_PROMPT.format(message)
        response = self.client.messages.create(
            model="claude-3-haiku-20240307", max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        return self._parse_json_response(response.content[0].text, message)

    def _parse_json_response(self, response_text: str, raw_message: str) -> ParsedOrder:
        try:
            json_match = re.search(r'(\{.*\})', response_text, re.DOTALL)
            data = json.loads(json_match.group(1)) if json_match else json.loads(response_text)
        except Exception:
            return self._basic_parse(raw_message)

        products = get_products()
        items = [
            OrderItem(products[i["product_code"].upper()], i["quantity"])
            for i in data.get("items", [])
            if i.get("product_code", "").upper() in products
        ]
        total = sum(it.quantity * it.product.price for it in items)
        location = data.get("customer_location")
        auto_sold_by = "Ferdie" if location == "Quezon City" else "Nina" if location == "Paranaque" else None

        return ParsedOrder(
            customer_name=(data.get("customer_name") or "").title() or None,
            items=items, total_amount=total, raw_message=raw_message,
            payment_method=data.get("payment_method"), customer_location=location,
            auto_sold_by=auto_sold_by
        )

    def _basic_parse(self, message: str) -> ParsedOrder:
        products = get_products()
        items = []
        for qty, code in self._product_pattern.findall(message):
            code = code.upper()
            if code in products:
                items.append(OrderItem(products[code], int(qty)))
        total = sum(it.quantity * it.product.price for it in items)
        return ParsedOrder(None, items, total, message)


# -----------------------------
# Google Sheets Integration
# -----------------------------
class GoogleSheetsIntegration:
    def __init__(self):
        self.worksheet = None

    def connect(self, spreadsheet_id: str, worksheet_name: str = "ORDER") -> bool:
        try:
            creds_data = json.loads(st.secrets["GOOGLE_CREDENTIALS"]) \
                if "GOOGLE_CREDENTIALS" in st.secrets else \
                json.load(open("google_credentials.json"))
            creds = Credentials.from_service_account_info(creds_data, scopes=[
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive'
            ])
            self.worksheet = gspread.authorize(creds).open_by_key(spreadsheet_id).worksheet(worksheet_name)
            return True
        except Exception as e:
            st.error(f"Google Sheets connection failed: {e}")
            return False

    def find_next_available_row(self) -> int:
        col_values = self.worksheet.col_values(4)  # Customer name column D
        return len(col_values) + 1

    def update_order(self, parsed: ParsedOrder, row: int) -> bool:
        try:
            today = datetime.now().strftime("%m/%d/%Y")
            updates = {
                'C': today, 'D': parsed.customer_name or "Unknown",
                'E': parsed.auto_sold_by or "", 'H': "Unpaid"
            }
            for item in parsed.items:
                col = PRODUCT_COLUMN_MAP.get(item.product.code)
                if col:
                    updates[col] = item.quantity
            for col, val in updates.items():
                self.worksheet.update_cell(row, ord(col) - 64, val)
            return True
        except Exception as e:
            st.error(f"Update failed: {e}")
            return False


# -----------------------------
# Claude Prompt Template
# -----------------------------
CLAUDE_PROMPT = """
You are an expert order parser...
CUSTOMER MESSAGE TO PARSE:
{}
"""

# -----------------------------
# Streamlit App
# -----------------------------
def main():
    st.title("Chickpea Chips Order Processor")
    spreadsheet_id = st.sidebar.text_input("Google Sheets ID", "1DGt5u6QWWIMRZmU1...")
    message = st.text_area("Paste FB Messenger message here")

    if st.button("🔄 Process Order") and message.strip():
        parser = OrderParser()
        parsed = parser.parse(message)
        st.write("### Parsed Order")
        st.json(parsed.__dict__)

        if st.button("📊 Update Google Sheet") and spreadsheet_id:
            sheets = GoogleSheetsIntegration()
            if sheets.connect(spreadsheet_id):
                row = sheets.find_next_available_row()
                if sheets.update_order(parsed, row):
                    st.success(f"Order added to row {row}")


if __name__ == "__main__":
    main()
