# KSML Basic Framework

KSML is a compact XML modeling format. 
This document defines the absolute minimum structural requirements. All other semantic validation, privacy rules, and regulatory compliance will be checked by the validation server.

## 1. Multi-File Layout with `<_include>`

For models with more than 10 objects, ALWAYS split into multiple files to avoid output truncation.

```xml
<!-- main.xml — entry point, contains ONLY root + includes -->
<?xml version="1.0" encoding="UTF-8"?>
<root name="example-service"
      data_service="sqlite"
      org="doublechaintech"
      _module_key="root">

  <_include file="operations.xml" />
  <_include file="users.xml" />
</root>
```

Each included file (e.g. `operations.xml`) MUST be a valid, standalone XML document.
To achieve this, wrap the objects in a `<root>` tag with a standard XML header:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<root>
  <some_object _name="Some Object" ... />
  <another_object _name="Another Object" ... />
</root>
```

This ensures every file is standard-compliant XML.
## 2. Basic Object Shape

Business objects use attributes for fields:
```xml
<employee _name="Employee"
          _module="HR" _module_key="hr"
          name="John Doe"
          phone="13800138000" />
```

Constant objects (enums) use `<_value>` children and MUST reference the domain root:
```xml
<user_status _name="User Status"
             _module="Platform" _module_key="platform"
             id="id()" name="string()" code="string()"
             _constant="true" _identifier="code"
             platform="platform()">
  <_value id="1001" name="Active" code="ACTIVE"/>
</user_status>
```

*Note: Do not worry about specific privacy fields (like CCPA/GDPR rules) — the domain validation server will instruct you on how to mask sensitive fields if you miss them.*
