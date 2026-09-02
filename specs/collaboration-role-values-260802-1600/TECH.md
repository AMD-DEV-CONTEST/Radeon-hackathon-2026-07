# Collaboration Role Value Fix — Technical Notes

- Level: S1
- Status: implemented

## Change

Set the HTML option value to the original API enum while retaining the Chinese
label as its displayed text in both role selectors.

## Risk and rollback

Low risk, limited to form serialization. Revert this change to restore the
previous behavior.
