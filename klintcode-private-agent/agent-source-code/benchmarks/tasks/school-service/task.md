# School Service Model

Generate a KSML XML model for a school management service with exactly 3 objects:

1. **School** — the root object
   - Properties: name (string), address (string), established_year (int)
   - Has children: Teacher (many), Student (many)

2. **Teacher** — belongs to School
   - Properties: name (string), subject (string), employee_id (string)
   - Container: School

3. **Student** — belongs to School
   - Properties: name (string), grade (int), enrollment_date (date)
   - Container: School

## Requirements
- Output a single complete XML document
- Follow the grammar example structure exactly
- Use only allowed value forms from the whitelist
- Include all 3 objects with their properties and relationships
- Each object must have proper internal_type, display_name, and _module_key
