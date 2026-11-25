# Module Name Mismatch Fix - Bugfix Design

## Overview

This bugfix addresses a critical AXERP installation failure caused by a module name mismatch between the `modules.txt` configuration file and the actual module folder structure. The bug has two components: an immediate fix to restore the correct module name, and a preventive fix to ensure the bug doesn't recur during future upstream syncs.

The immediate issue is that `modules.txt` lists "AXERP Integrations" while the actual folder is named `erpnext_integrations/` and all Python imports reference `erpnext.erpnext_integrations.*`. This mismatch causes Frappe to fail during app installation with a ModuleNotFoundError.

The root cause is the `scripts/smart_rename.py` script, which performs a global find-and-replace of "ERPNext" → "AXERP" during upstream syncs. This script inadvertently renames "ERPNext Integrations" to "AXERP Integrations" in configuration files without renaming the actual folder or updating import statements, creating the mismatch.

The fix strategy involves: (1) reverting the module name in `modules.txt` and affected JSON files back to "ERPNext Integrations", and (2) updating `smart_rename.py` to exclude the integrations module from rebranding operations.

## Glossary

- **Bug_Condition (C)**: The condition that triggers the bug - when the module name in `modules.txt` doesn't match the actual folder name and import paths
- **Property (P)**: The desired behavior - AXERP installation completes successfully and the integrations module remains accessible
- **Preservation**: Existing module functionality, import statements, and the rebranding script's behavior for all other modules must remain unchanged
- **modules.txt**: Configuration file at `erpnext/modules.txt` that lists all available modules in the AXERP app
- **erpnext_integrations/**: The actual folder containing the integrations module code
- **smart_rename.py**: Script at `scripts/smart_rename.py` that performs global rebranding during upstream syncs
- **Module Field**: The "module" property in DocType JSON files that associates a doctype with its parent module

## Bug Details

### Fault Condition

The bug manifests when Frappe attempts to install the AXERP app and encounters a module name in `modules.txt` that doesn't correspond to an actual importable Python module. The installation process reads "AXERP Integrations" from `modules.txt`, attempts to import it as `erpnext.axerp_integrations`, but fails because the actual folder is named `erpnext_integrations/` (not `axerp_integrations/`).

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type ModuleInstallationAttempt
  OUTPUT: boolean
  
  RETURN input.moduleNameInConfig == "AXERP Integrations"
         AND input.actualFolderName == "erpnext_integrations"
         AND input.existingImportStatements CONTAIN "erpnext.erpnext_integrations"
         AND NOT canImportModule("erpnext.axerp_integrations")
END FUNCTION
```

### Examples

- **Installation Failure**: Running `bench --site mysite install-app erpnext` raises `ModuleNotFoundError: No module named 'erpnext.axerp_integrations'` because Frappe tries to import the module listed in `modules.txt` but the folder doesn't match
- **Import Resolution Failure**: Existing code with `from erpnext.erpnext_integrations.doctype.plaid_settings.plaid_settings import ...` works correctly, but the module name mismatch prevents Frappe from recognizing the module during installation
- **JSON Module Field Mismatch**: The file `erpnext/erpnext_integrations/doctype/plaid_settings/plaid_settings.json` has `"module": "AXERP Integrations"` which doesn't match the folder structure
- **Recurring Bug**: After fixing `modules.txt` manually, running `scripts/sync_upstream.sh` (which calls `smart_rename.py`) re-introduces the bug by changing "ERPNext Integrations" to "AXERP Integrations"

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- All other modules (Accounts, CRM, Buying, etc.) must continue to install and function correctly
- Existing Python imports from `erpnext.erpnext_integrations.*` must continue to resolve correctly
- The `smart_rename.py` script must continue to rebrand all other modules and content (changing "ERPNext" to "AXERP" everywhere except the integrations module)
- All existing integrations functionality, doctypes, and features must continue to work without modification
- The upstream sync process must continue to function correctly for all other operations

**Scope:**
All inputs that do NOT involve the integrations module should be completely unaffected by this fix. This includes:
- Installation and usage of all other AXERP modules
- Rebranding operations for all other modules and content
- Existing code that doesn't reference the integrations module
- The overall upstream sync workflow

## Hypothesized Root Cause

Based on the bug description and code analysis, the root cause is clear:

1. **Incomplete Rebranding Logic**: The `smart_rename.py` script performs a naive global find-and-replace of "ERPNext" → "AXERP" across all files with target extensions (`.json`, `.py`, `.js`, `.html`, `.csv`, `.txt`, `.md`). This changes "ERPNext Integrations" to "AXERP Integrations" in `modules.txt` without considering the implications.

2. **No Folder Renaming**: The script does not rename the `erpnext_integrations/` folder to `axerp_integrations/`, leaving a mismatch between the configuration and the actual file system structure.

3. **No Import Statement Updates**: The script does not update Python import statements like `from erpnext.erpnext_integrations.*` to match the renamed module, leaving hundreds of import references pointing to the original module path.

4. **Recurring Execution**: The script runs automatically during every upstream sync (called by `scripts/sync_upstream.sh`), which means any manual fix to `modules.txt` gets overwritten on the next sync.

5. **Missing Exclusion Logic**: The script lacks any mechanism to exclude specific modules or patterns from rebranding, making it impossible to preserve "ERPNext Integrations" while rebranding everything else.

## Correctness Properties

Property 1: Fault Condition - Module Name Matches Folder Structure

_For any_ installation attempt where the AXERP app is being installed, the fixed configuration SHALL have "ERPNext Integrations" in `modules.txt` matching the actual folder name `erpnext_integrations/` and all existing import statements, allowing Frappe to successfully import and install the module without ModuleNotFoundError.

**Validates: Requirements 2.1, 2.2, 2.3**

Property 2: Preservation - Script Prevents Future Damage

_For any_ execution of `smart_rename.py` (including during upstream syncs), the fixed script SHALL preserve "ERPNext Integrations" in all configuration files, JSON module fields, folder names, and import statements while continuing to rebrand all other content from "ERPNext" to "AXERP".

**Validates: Requirements 2.4, 2.5, 2.6, 2.7, 2.8, 3.6, 3.7, 3.8, 3.9**

Property 3: Preservation - Existing Module Functionality

_For any_ usage of the integrations module or other AXERP modules, the fixed code SHALL produce exactly the same behavior as the original code, preserving all module functionality, import resolution, and data integrity.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

## Fix Implementation

### Changes Required

Based on the root cause analysis, we need to make three specific changes:

**File 1**: `erpnext/modules.txt`

**Change**: Revert module name from "AXERP Integrations" to "ERPNext Integrations"

**Specific Changes**:
1. **Line 15**: Change `AXERP Integrations` to `ERPNext Integrations`
   - This restores the correct module name that matches the folder structure
   - Allows Frappe to successfully import `erpnext.erpnext_integrations` during installation

**File 2**: `erpnext/erpnext_integrations/doctype/plaid_settings/plaid_settings.json`

**Change**: Revert module field from "AXERP Integrations" to "ERPNext Integrations"

**Specific Changes**:
1. **Line 75**: Change `"module": "AXERP Integrations"` to `"module": "ERPNext Integrations"`
   - Ensures DocType metadata matches the actual module name
   - Maintains consistency across all module references

**File 3**: `scripts/smart_rename.py`

**Function**: `run_rebrand()`

**Specific Changes**:
1. **Add Exclusion Logic for modules.txt**: Before processing `modules.txt`, add logic to preserve "ERPNext Integrations" line
   - Read the file line by line
   - Skip rebranding for lines containing "ERPNext Integrations"
   - Apply rebranding to all other lines

2. **Add Exclusion Logic for JSON Files**: When processing JSON files, add logic to preserve module fields with "ERPNext Integrations"
   - Check if the file is a DocType JSON (contains `"module":` field)
   - Skip rebranding for `"module": "ERPNext Integrations"` patterns
   - Apply rebranding to all other content

3. **Add Exclusion Pattern**: Define a constant for the exclusion pattern
   - Add `PRESERVE_INTEGRATIONS_MODULE = "ERPNext Integrations"` constant
   - Use this constant throughout the exclusion logic for consistency

4. **Update File Processing Loop**: Modify the main file processing loop to apply exclusions
   - For `modules.txt` specifically, use line-by-line processing with exclusion
   - For JSON files, use pattern-aware replacement that preserves module fields
   - For all other files, continue with existing global replacement logic

5. **Add Comments**: Document the exclusion logic with clear comments explaining why the integrations module must be preserved

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, demonstrate the bug on the unfixed code to confirm the root cause, then verify the fix works correctly and preserves existing behavior. Testing will focus on three areas: installation success, script behavior, and preservation of existing functionality.

### Exploratory Fault Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm that the module name mismatch causes installation failure and that `smart_rename.py` is the root cause.

**Test Plan**: Attempt to install AXERP with the current (buggy) configuration, observe the ModuleNotFoundError, then run `smart_rename.py` on a test copy of the files to confirm it re-introduces the bug. Run these tests on the UNFIXED code to observe failures and validate the root cause hypothesis.

**Test Cases**:
1. **Installation Failure Test**: Run `bench --site test-site install-app erpnext` with "AXERP Integrations" in modules.txt (will fail on unfixed code with ModuleNotFoundError)
2. **Import Resolution Test**: Attempt to import `erpnext.axerp_integrations` in Python (will fail on unfixed code because folder is named `erpnext_integrations`)
3. **Script Damage Test**: Manually fix modules.txt to "ERPNext Integrations", run `smart_rename.py`, verify it changes to "AXERP Integrations" (will demonstrate recurring bug on unfixed code)
4. **JSON Module Field Test**: Check `plaid_settings.json` for module field value (will show "AXERP Integrations" on unfixed code)

**Expected Counterexamples**:
- AXERP installation fails with `ModuleNotFoundError: No module named 'erpnext.axerp_integrations'`
- Python cannot import `erpnext.axerp_integrations` but can import `erpnext.erpnext_integrations`
- Running `smart_rename.py` changes "ERPNext Integrations" to "AXERP Integrations" in modules.txt
- Possible causes: global find-and-replace without exclusions, no folder renaming, no import statement updates

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds (module name mismatch scenarios), the fixed configuration and script produce the expected behavior (successful installation and preserved module name).

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := installAXERP_fixed(input)
  ASSERT result.installationSucceeds == true
  ASSERT result.moduleImportable == true
  ASSERT result.modulesTextContains("ERPNext Integrations") == true
END FOR
```

**Test Cases**:
1. **Fresh Installation Test**: Install AXERP on a new site with fixed modules.txt, verify installation completes successfully
2. **Module Import Test**: Verify `erpnext.erpnext_integrations` can be imported after fix
3. **Script Preservation Test**: Run fixed `smart_rename.py`, verify "ERPNext Integrations" remains unchanged in modules.txt
4. **JSON Preservation Test**: Run fixed `smart_rename.py`, verify module field in plaid_settings.json remains "ERPNext Integrations"
5. **Upstream Sync Test**: Run full `sync_upstream.sh` workflow, verify integrations module remains intact

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold (other modules, other rebranding operations), the fixed code produces the same result as the original code.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT originalBehavior(input) = fixedBehavior(input)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many test cases automatically across the input domain (different modules, different file types, different content patterns)
- It catches edge cases that manual unit tests might miss (unusual module names, special characters, nested references)
- It provides strong guarantees that behavior is unchanged for all non-buggy inputs (all modules except integrations)

**Test Plan**: Observe behavior on UNFIXED code first for other modules and rebranding operations, then write property-based tests capturing that behavior to ensure the fix doesn't break anything.

**Test Cases**:
1. **Other Modules Installation**: Verify all other modules (Accounts, CRM, Buying, etc.) install successfully after fix
2. **Rebranding Preservation**: Verify `smart_rename.py` continues to rename "ERPNext Assets" to "AXERP Assets" and other modules correctly
3. **Import Statement Preservation**: Verify existing imports like `from erpnext.erpnext_integrations.doctype.plaid_settings.plaid_settings import ...` continue to work
4. **Integrations Functionality**: Verify Plaid Settings and other integrations features continue to function correctly
5. **JSON Rebranding**: Verify other JSON files (not integrations module) continue to be rebranded correctly

### Unit Tests

- Test AXERP installation with correct module name in modules.txt
- Test that `erpnext.erpnext_integrations` module can be imported
- Test `smart_rename.py` exclusion logic for "ERPNext Integrations" pattern
- Test that modules.txt line with "ERPNext Integrations" is preserved during rebranding
- Test that JSON module fields with "ERPNext Integrations" are preserved during rebranding
- Test that other module names are still rebranded correctly (e.g., "ERPNext Assets" → "AXERP Assets")

### Property-Based Tests

- Generate random module configurations and verify installation succeeds when module names match folder structure
- Generate random file content with "ERPNext" patterns and verify `smart_rename.py` renames everything except "ERPNext Integrations"
- Generate random JSON files with module fields and verify integrations module is preserved while others are rebranded
- Test across many upstream sync scenarios to verify integrations module remains intact

### Integration Tests

- Test full AXERP installation workflow from start to finish with fixed configuration
- Test complete upstream sync workflow (`sync_upstream.sh`) and verify integrations module remains functional
- Test that existing sites with integrations data continue to work after applying the fix
- Test that all integrations features (Plaid, etc.) continue to function correctly after fix
