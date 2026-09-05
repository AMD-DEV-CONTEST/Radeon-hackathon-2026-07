# School Service Model (Rust Build Test)

Generate a KSML XML model for a simple school management system.
You MUST generate EXACTLY 3 objects.

## Required Objects
1. School - root entity with name, address, create_time, update_time
2. Teacher - belongs to school, has name, subject, email, create_time, update_time
3. Student - belongs to school, has name, grade (int), enrollment_date (date), create_time, update_time

## Requirements
- Follow the grammar example structure exactly.
- Use only allowed value forms from the whitelist.
- You MUST generate exactly 3 objects. No more, no less.
- Each object must have proper _name, _module, and _module_key.
- Include relationships between objects (school is parent of teacher and student).
- Keep all objects in a single main.xml file (no includes needed for 3 objects).

CRITICAL: NEVER use reserved keywords like 'type' for field names. Use descriptive alternatives like 'subject_area' instead.
