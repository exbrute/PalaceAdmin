"""Telegram Android Icons (TgAndroidIcons) custom emoji helpers."""

from __future__ import annotations

from html import escape

# https://t.me/addemoji/TgAndroidIcons
IDS: dict[str, str] = {
    "home": "5967822972931542886",
    "cancel": "5778527486270770928",
    "help": "5873121512445187130",
    "money_bag": "5811989245761426317",
    "money": "5967390100357648692",
    "date": "5967412305338568701",
    "warning": "5881702736843511327",
    "person": "5771887475421090729",
    "link": "5877465816030515018",
    "plus": "5877219383691972108",
    "people": "5915556996215476302",
    "chart": "5877485980901971030",
    "megaphone": "5771695636411847302",
    "trash": "5879896690210639947",
    "page": "5839323457015256759",
    "test": "5897607722295103204",
    "check": "5776375003280838798",
    "lock": "5832546462478635761",
    "prohibited": "5872829476143894491",
    "party": "5994502837327892086",
    "wave": "5994750571041525522",
    "book": "5897850551156084824",
    "tools": "5988023995125993550",
    "memo": "5886330010054168711",
    "red": "5967333011652350314",
    "chart_up": "5776219138917668486",
    "card": "5967548335542767952",
    "refresh": "5839200986022812209",
    "gear": "5877260593903177342",
    "burger": "5875271289605722323",
    "folder": "5875462364110787088",
    "magnifier": "5874960879434338403",
    "label": "5854776233950188167",
    "newspaper": "5886506997066502636",
    "picture": "5888799736508454231",
    "phone": "5985833664884250583",
    "info": "5879785854284599288",
    "thumbs_up": "5992199545151295755",
}

FALLBACK: dict[str, str] = {
    "home": "🏠",
    "cancel": "❌",
    "help": "❓",
    "money_bag": "💰",
    "money": "💵",
    "date": "📅",
    "warning": "⚠️",
    "person": "👤",
    "link": "🔗",
    "plus": "➕",
    "people": "👥",
    "chart": "📊",
    "megaphone": "📢",
    "trash": "🗑",
    "page": "📄",
    "test": "🧪",
    "check": "✅",
    "lock": "🔒",
    "prohibited": "🚫",
    "party": "🎉",
    "wave": "👋",
    "book": "📖",
    "tools": "🛠",
    "memo": "📝",
    "red": "🔴",
    "chart_up": "📈",
    "card": "💳",
    "refresh": "🔄",
    "gear": "🕐",
    "burger": "🍹",
    "folder": "📋",
    "magnifier": "🔍",
    "label": "➖",
    "newspaper": "📰",
    "picture": "🖼",
    "phone": "📱",
    "info": "ℹ️",
    "thumbs_up": "👍",
}


def e(key: str) -> str:
    emoji_id = IDS[key]
    fallback = FALLBACK.get(key, "•")
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'


def h(text: str | int | float) -> str:
    return escape(str(text))


def icon_id(key: str) -> str:
    return IDS[key]
