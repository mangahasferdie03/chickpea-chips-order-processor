import os
from typing import Dict, Any
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from order_parser import OrderParser
from sheets_client import GoogleSheetsClient

class OrderBot:
    def __init__(self):
        self.parser = OrderParser()
        self.sheets_client = GoogleSheetsClient()
        
        # Product catalog for price lookups
        self.products = {
            'P-CHZ': {'name': 'Cheese', 'size': 'Pouch', 'price': 150},
            'P-SC': {'name': 'Sour Cream', 'size': 'Pouch', 'price': 150},
            'P-BBQ': {'name': 'BBQ', 'size': 'Pouch', 'price': 150},
            'P-OG': {'name': 'Original Blend', 'size': 'Pouch', 'price': 150},
            '2L-CHZ': {'name': 'Cheese', 'size': 'Tub', 'price': 290},
            '2L-SC': {'name': 'Sour Cream', 'size': 'Tub', 'price': 290},
            '2L-BBQ': {'name': 'BBQ', 'size': 'Tub', 'price': 290},
            '2L-OG': {'name': 'Original Spice Blend', 'size': 'Tub', 'price': 290}
        }

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send a message when the command /start is issued."""
        await update.message.reply_text(
            "🤖 Welcome to Preetos Order Parser Bot!\n\n"
            "Simply paste your Facebook Messenger orders here and I'll:\n"
            "✅ Parse the order details\n"
            "📊 Add them to your Google Sheets\n"
            "📋 Generate a customer breakdown\n\n"
            "Just send me an order message to get started!"
        )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send a message when the command /help is issued."""
        help_text = """
🤖 **Preetos Order Parser Bot Help**

**How to use:**
1. Copy your Facebook Messenger order
2. Paste it in this chat
3. Get parsed results + customer breakdown

**Supported formats:**
• Customer names
• Product orders (pouches/tubs, cheese/sour cream/bbq/original)
• Payment methods (Gcash, BPI, Maya, Cash, BDO)
• Locations (QC = Quezon City, Paranaque)
• Shipping fees (sf 100, delivery 50, etc.)
• Discounts (5%, 10 off, etc.)
• Filipino/Taglish text

**Commands:**
/start - Welcome message
/help - This help message

Just paste your orders and let me handle the rest! 🚀
        """
        await update.message.reply_text(help_text)

    async def handle_order(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming order messages"""
        user_message = update.message.text
        
        try:
            # Show processing message
            processing_msg = await update.message.reply_text("🔄 Processing your order...")
            
            # Parse the order
            parsed_order = self.parser.parse_order(user_message)
            
            # Delete processing message
            await processing_msg.delete()
            
            # Store parsed order in context for later use
            context.user_data['pending_order'] = parsed_order
            
            # Send parsed results summary with confirmation buttons
            await self._send_parsed_results_with_buttons(update, context, parsed_order)
            
        except Exception as e:
            await update.message.reply_text(f"❌ Error processing order: {str(e)}")

    async def handle_confirmation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle confirm/cancel button presses"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "confirm_order":
            # Get the pending order
            parsed_order = context.user_data.get('pending_order')
            if not parsed_order:
                await query.edit_message_text("❌ No pending order found.")
                return
            
            try:
                # Insert into Google Sheets
                sheets_success = self.sheets_client.insert_order(parsed_order)
                
                if not sheets_success:
                    await query.edit_message_text("❌ Failed to add order to Google Sheets.")
                    return
                
                # Update the first message to show it was confirmed
                await self._update_confirmed_summary(query, parsed_order)
                
                # Send customer breakdown
                await self._send_customer_breakdown_from_callback(query, parsed_order)
                
                # Clear pending order
                context.user_data.pop('pending_order', None)
                
            except Exception as e:
                await query.edit_message_text(f"❌ Error confirming order: {str(e)}")
                
        elif query.data == "cancel_order":
            await query.edit_message_text("❌ Order cancelled.")
            # Clear pending order
            context.user_data.pop('pending_order', None)

    async def _send_parsed_results_with_buttons(self, update: Update, context: ContextTypes.DEFAULT_TYPE, parsed_order: Dict[str, Any]):
        """Send parsed results summary with confirm/cancel buttons"""
        
        # Calculate totals
        subtotal = 0
        if parsed_order.get('items'):
            for item in parsed_order['items']:
                product_code = item['product_code']
                quantity = item['quantity']
                product_info = self.products.get(product_code, {})
                price = product_info.get('price', 0)
                subtotal += quantity * price
        
        # Calculate final total
        final_total = subtotal
        if parsed_order.get('shipping_fee'):
            final_total += parsed_order['shipping_fee']
        if parsed_order.get('discount_amount'):
            final_total -= parsed_order['discount_amount']
        
        # Build the summary message
        summary_lines = ["✅ **Order Successfully Processed!**", ""]
        
        # Customer info
        if parsed_order.get('customer_name'):
            summary_lines.append(f"**Customer:** {parsed_order['customer_name']}")
        
        # Payment method and status
        payment_info = []
        if parsed_order.get('payment_method'):
            payment_info.append(parsed_order['payment_method'])
        if parsed_order.get('payment_status'):
            payment_info.append(f"({parsed_order['payment_status']})")
        if payment_info:
            summary_lines.append(f"**Payment:** {' '.join(payment_info)}")
        
        # Location
        if parsed_order.get('customer_location'):
            summary_lines.append(f"**Location:** {parsed_order['customer_location']}")
        
        # Items
        if parsed_order.get('items'):
            summary_lines.append("**Items:**")
            for item in parsed_order['items']:
                product_code = item['product_code']
                quantity = item['quantity']
                product_info = self.products.get(product_code, {})
                size = product_info.get('size', 'Unknown')
                name = product_info.get('name', product_code)
                summary_lines.append(f"  • {quantity}x {size} {name}")
        
        # Shipping fee
        if parsed_order.get('shipping_fee'):
            summary_lines.append(f"**Shipping:** ₱{parsed_order['shipping_fee']}")
        
        # Discount
        if parsed_order.get('discount_percentage'):
            summary_lines.append(f"**Discount ({parsed_order['discount_percentage']}%):** ₱{parsed_order['discount_amount']}")
        elif parsed_order.get('discount_amount'):
            summary_lines.append(f"**Discount:** ₱{parsed_order['discount_amount']} off")
        
        # Final total
        summary_lines.append("")
        summary_lines.append(f"**Final Total:** ₱{final_total}")
        
        message_text = "\n".join(summary_lines)
        
        # Create inline keyboard with Confirm/Cancel buttons
        keyboard = [
            [
                InlineKeyboardButton("✅ Confirm", callback_data="confirm_order"),
                InlineKeyboardButton("❌ Cancel", callback_data="cancel_order")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(message_text, parse_mode='Markdown', reply_markup=reply_markup)

    async def _update_confirmed_summary(self, query, parsed_order: Dict[str, Any]):
        """Update the summary message after confirmation"""
        
        # Calculate totals
        subtotal = 0
        if parsed_order.get('items'):
            for item in parsed_order['items']:
                product_code = item['product_code']
                quantity = item['quantity']
                product_info = self.products.get(product_code, {})
                price = product_info.get('price', 0)
                subtotal += quantity * price
        
        # Calculate final total
        final_total = subtotal
        if parsed_order.get('shipping_fee'):
            final_total += parsed_order['shipping_fee']
        if parsed_order.get('discount_amount'):
            final_total -= parsed_order['discount_amount']
        
        # Build the updated summary message (same content, no buttons)
        summary_lines = ["✅ **Order Successfully Processed!**", ""]
        
        # Customer info
        if parsed_order.get('customer_name'):
            summary_lines.append(f"**Customer:** {parsed_order['customer_name']}")
        
        # Payment method and status
        payment_info = []
        if parsed_order.get('payment_method'):
            payment_info.append(parsed_order['payment_method'])
        if parsed_order.get('payment_status'):
            payment_info.append(f"({parsed_order['payment_status']})")
        if payment_info:
            summary_lines.append(f"**Payment:** {' '.join(payment_info)}")
        
        # Location
        if parsed_order.get('customer_location'):
            summary_lines.append(f"**Location:** {parsed_order['customer_location']}")
        
        # Items
        if parsed_order.get('items'):
            summary_lines.append("**Items:**")
            for item in parsed_order['items']:
                product_code = item['product_code']
                quantity = item['quantity']
                product_info = self.products.get(product_code, {})
                size = product_info.get('size', 'Unknown')
                name = product_info.get('name', product_code)
                summary_lines.append(f"  • {quantity}x {size} {name}")
        
        # Shipping fee
        if parsed_order.get('shipping_fee'):
            summary_lines.append(f"**Shipping:** ₱{parsed_order['shipping_fee']}")
        
        # Discount
        if parsed_order.get('discount_percentage'):
            summary_lines.append(f"**Discount ({parsed_order['discount_percentage']}%):** ₱{parsed_order['discount_amount']}")
        elif parsed_order.get('discount_amount'):
            summary_lines.append(f"**Discount:** ₱{parsed_order['discount_amount']} off")
        
        # Final total
        summary_lines.append("")
        summary_lines.append(f"**Final Total:** ₱{final_total}")
        
        message_text = "\n".join(summary_lines)
        
        await query.edit_message_text(message_text, parse_mode='Markdown')

    async def _send_customer_breakdown(self, update: Update, parsed_order: Dict[str, Any]):
        """Send the enhanced customer breakdown in the specified format"""
        
        breakdown_lines = []
        subtotal = 0
        
        # Items with prices in the exact format specified
        if parsed_order.get('items'):
            for item in parsed_order['items']:
                product_code = item['product_code']
                quantity = item['quantity']
                product_info = self.products.get(product_code, {})
                
                size = product_info.get('size', 'Unknown')
                name = product_info.get('name', product_code)
                price = product_info.get('price', 0)
                line_total = quantity * price
                subtotal += line_total
                
                # Format: "Pouch Cheese - 1 - ₱150"
                breakdown_lines.append(f"{size} {name} - {quantity} - ₱{price}")
        
        # Add shipping fee if present
        total = subtotal
        if parsed_order.get('shipping_fee'):
            shipping_fee = parsed_order['shipping_fee']
            breakdown_lines.append(f"Shipping Fee: ₱{shipping_fee}")
            total += shipping_fee
        
        # Add discount if present
        if parsed_order.get('discount_amount'):
            discount_amount = parsed_order['discount_amount']
            if parsed_order.get('discount_percentage'):
                discount_percentage = parsed_order['discount_percentage']
                breakdown_lines.append(f"Discount ({discount_percentage}%): -₱{discount_amount}")
            else:
                breakdown_lines.append(f"Discount: -₱{discount_amount}")
            total -= discount_amount
        
        # Add separator and final total
        breakdown_lines.append("----------")
        breakdown_lines.append(f"Total - ₱{total:,.2f}".replace('.00', ''))
        
        # Send the clean breakdown message without any bot formatting
        customer_message = "\n".join(breakdown_lines)
        await update.message.reply_text(customer_message)

    async def _send_customer_breakdown_from_callback(self, query, parsed_order: Dict[str, Any]):
        """Send the enhanced customer breakdown from a callback query"""
        
        breakdown_lines = []
        subtotal = 0
        
        # Items with prices in the exact format specified
        if parsed_order.get('items'):
            for item in parsed_order['items']:
                product_code = item['product_code']
                quantity = item['quantity']
                product_info = self.products.get(product_code, {})
                
                size = product_info.get('size', 'Unknown')
                name = product_info.get('name', product_code)
                price = product_info.get('price', 0)
                line_total = quantity * price
                subtotal += line_total
                
                # Format: "Pouch Cheese - 1 - ₱150"
                breakdown_lines.append(f"{size} {name} - {quantity} - ₱{price}")
        
        # Add shipping fee if present
        total = subtotal
        if parsed_order.get('shipping_fee'):
            shipping_fee = parsed_order['shipping_fee']
            breakdown_lines.append(f"Shipping Fee: ₱{shipping_fee}")
            total += shipping_fee
        
        # Add discount if present
        if parsed_order.get('discount_amount'):
            discount_amount = parsed_order['discount_amount']
            if parsed_order.get('discount_percentage'):
                discount_percentage = parsed_order['discount_percentage']
                breakdown_lines.append(f"Discount ({discount_percentage}%): -₱{discount_amount}")
            else:
                breakdown_lines.append(f"Discount: -₱{discount_amount}")
            total -= discount_amount
        
        # Add separator and final total
        breakdown_lines.append("----------")
        breakdown_lines.append(f"Total - ₱{total:,.2f}".replace('.00', ''))
        
        # Send the clean breakdown message without any bot formatting
        customer_message = "\n".join(breakdown_lines)
        await query.message.reply_text(customer_message)

def create_application():
    """Create and configure the Telegram application"""
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")
    
    # Create application
    application = Application.builder().token(token).build()
    
    # Create bot instance
    bot = OrderBot()
    
    # Add handlers
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("help", bot.help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_order))
    application.add_handler(CallbackQueryHandler(bot.handle_confirmation))
    
    return application