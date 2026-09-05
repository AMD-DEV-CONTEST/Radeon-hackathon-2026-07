# Online Bookstore Service Model (3 Objects)

Generate a KSML XML model for a simple online bookstore.
You MUST generate EXACTLY 3 objects.

## Domain

A small bookstore system with:
- **Bookstore**: The store entity (name, address, phone)
- **Book**: Books sold by the store (title, author, ISBN, price, stock count)
- **Book Category**: A constant/enum categorizing books (Fiction, Non-Fiction, Science, History, etc.)

## Requirements

- Follow the grammar example structure exactly.
- Use only allowed value forms from the whitelist.
- You MUST generate exactly 3 objects. No more, no less.
- Each object must have proper `_name`, `_module`, and `_module_key`.
- `book_category` must be a constant object with `id="id()"`, `_constant="true"`, `_identifier="code"`, and at least 4 `<_value>` children.
- `book` must reference `bookstore` via `bookstore="bookstore()"` and `category` via `category="book_category()"`.
- Output raw XML only. No markdown fences.
