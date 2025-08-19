import re
from decimal import Decimal, InvalidOperation


def clean_price(price_str: str | None) -> Decimal | None:
    """
    Cleans a price string by removing currency symbols and commas, converting it to a Decimal.

    Args:
        price_str (str | None): The raw price string to clean.

    Returns:
        Decimal | None: The cleaned price as a Decimal, or None if the input is invalid.
    """
    if price_str is None:
        return None

    if isinstance(price_str, (int, float, Decimal)):
        return Decimal(str(price_str))

    if isinstance(price_str, str):
        try:
            cleaned_str = re.sub(r'[^\d.]', '', price_str)
            if cleaned_str.count('.') > 1:
                parts = cleaned_str.split('.')
                cleaned_str = parts[0] + '.' + ''.join(parts[1:])
            if not cleaned_str:
                return None
            return Decimal(cleaned_str)
        except (InvalidOperation, TypeError):
            return None
    return None

