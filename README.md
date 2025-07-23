# Chickpea Chips Order Processor

A Streamlit web application for automating chickpea chips order processing from Facebook Messenger messages with Google Sheets integration.

## Features

- **Simple Web Interface**: Clean interface for pasting customer messages
- **Claude API Integration**: Intelligent parsing of Filipino-English customer orders
- **Google Sheets Integration**: Automatic order updates to Google Sheets
- **Payment Method Detection**: Auto-detects GCash, BPI, Maya, Cash, BDO, Others
- **Location-Based Assignment**: Auto-assigns to Ferdie (QC) or Nina (Paranaque) 
- **Product Catalog**: Supports 8 products (4 flavors × 2 sizes)
- **Smart Row Detection**: Automatically finds next available row in sheets
- **Export Functionality**: Download orders as JSON

## Product Catalog

### Pouches (₱150 each)
- P-CHZ: Cheese
- P-SC: Sour Cream  
- P-BBQ: BBQ
- P-OG: Original

### Tubs (₱290 each)
- 2L-CHZ: Cheese
- 2L-SC: Sour Cream
- 2L-BBQ: BBQ
- 2L-OG: Original

## Installation

1. Install Python dependencies:
```bash
pip install -r requirements.txt
```

2. Run the application:
```bash
streamlit run app.py
```

3. Open your browser to `http://localhost:8501`

## Usage

1. **Configure API Key**: Enter your Anthropic Claude API key in the sidebar (optional - basic parsing works without it)

2. **Paste Customer Message**: Copy and paste Facebook Messenger conversations into the text area

3. **Process Order**: Click "Process Order" to parse the message

4. **Review Results**: Check the parsed customer name, items, quantities, and total

5. **Export Data**: Download the order data as JSON for record keeping

## Setup Files

The application requires two credential files:

1. **claude api.txt**: Contains your Anthropic Claude API key
2. **google_credentials.json**: Google Sheets service account credentials

## Google Sheets Integration

The app automatically:
- Detects the next available row in your Google Sheet
- Fills customer info, payment method, location, and product quantities
- Assigns orders to correct person based on location (QC→Ferdie, Paranaque→Nina)
- Marks orders as "Reserved" and adds 🤖 emoji to indicate web processing

## Example Messages

The parser can handle various message formats:

```
Hi! I'd like to order 2 cheese pouches and 1 BBQ tub please. 
This is for Maria Santos.
```

```
Order for John:
- 3x P-CHZ
- 2x 2L-SC
- 1x P-BBQ
```

## Error Handling

- Invalid product codes are ignored
- Missing customer names are flagged as warnings
- API failures fall back to basic parsing
- Empty messages show helpful prompts