"""XP Telegram bot package.

Security stance (architecture: Telegram Bot responsibilities):
- Never request or accept seed phrases or private keys in chat.
- Commands route users to the Mini App for anything security-sensitive.
"""
