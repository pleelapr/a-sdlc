# Deployment Guide: Standardized Command Names

**Status**: Ready for deployment
**Version**: Effective immediately

---

## What Changed?

All multi-word slash commands now use **hyphenated format** for better clarity and consistency:

### Before vs After

**PRD Commands:**
- ~~`/sdlc:prd generate`~~ → `/sdlc:prd-generate` ✅
- ~~`/sdlc:prd list`~~ → `/sdlc:prd-list` ✅
- ~~`/sdlc:prd update`~~ → `/sdlc:prd-update` ✅

**Task Commands:**
- ~~`/sdlc:task split`~~ → `/sdlc:task-split` ✅
- ~~`/sdlc:task list`~~ → `/sdlc:task-list` ✅
- ~~`/sdlc:task show`~~ → `/sdlc:task-show` ✅
- ~~`/sdlc:task start`~~ → `/sdlc:task-start` ✅
- ~~`/sdlc:task complete`~~ → `/sdlc:task-complete` ✅
- ~~`/sdlc:task create`~~ → `/sdlc:task-create` ✅
- ~~`/sdlc:task link`~~ → `/sdlc:task-link` ✅

**Note**: Single-word commands remain unchanged:
- `/sdlc:init`, `/sdlc:scan`, `/sdlc:status`, `/sdlc:update`, `/sdlc:help`, `/sdlc:publish`

---

## Why This Change?

✅ **Clearer hierarchy**: Command vs subcommand distinction
✅ **Better autocomplete**: Commands group logically in Claude Code
✅ **Industry standard**: Matches modern CLIs (git, gh, aws, docker)
✅ **No ambiguity**: Clear command boundaries

---

## How to Deploy

### Option 1: Quick Update (Recommended)

If you already have a-sdlc installed:

```bash
a-sdlc install --force
```

This updates your Claude Code skills directory with the latest templates.

### Option 2: Fresh Installation

If installing for the first time:

```bash
# Install package
uv tool install --force --editable ".[all]"

# Deploy skills
a-sdlc install --force
```

---

## Verification

After deployment, verify commands work in Claude Code:

### Test PRD Commands

```
/sdlc:prd-generate "Add OAuth authentication"
/sdlc:prd-list
```

### Test Task Commands

```
/sdlc:task-list
/sdlc:task-start TASK-001
```

### Check Autocomplete

Type `/sdlc:` in Claude Code and verify:
- All commands appear with hyphens
- Commands group logically (prd-*, task-*)
- Autocomplete suggestions are clear

---

## Troubleshooting

### Issue: Old commands still showing in Claude Code

**Symptoms**:
- Still seeing `/sdlc:prd generate` instead of `/sdlc:prd-generate`
- Autocomplete shows old format

**Solution**:
```bash
a-sdlc install --force
```

This overwrites the old templates in `~/.claude/commands/sdlc/` with the updated versions.

### Issue: `a-sdlc: command not found`

**Symptoms**:
- Can't run `a-sdlc install`

**Solution**:
```bash
# Install as a uv tool
uv tool install --force ".[all]"

# Or use Python directly
python3 -m a_sdlc.cli install --force
```

### Issue: Commands don't work after update

**Symptoms**:
- Commands not recognized in Claude Code
- Autocomplete shows commands but they don't execute

**Solution**:
1. Check installation location:
   ```bash
   ls ~/.claude/commands/sdlc/
   ```
2. Verify templates exist with correct format:
   ```bash
   grep "/sdlc:prd-" ~/.claude/commands/sdlc/prd.md
   ```
3. Restart Claude Code (usually not needed, but try if issues persist)

---

## Migration Timeline

**Phase 1**: ✅ **Complete** - Source code standardized
**Phase 2**: 🔄 **In Progress** - User deployment
**Phase 3**: 📅 **Planned** - Documentation updates

---

## Impact Assessment

**Breaking Change**: Yes (command names changed)
**User Action Required**: Yes (run `a-sdlc install --force`)
**Risk Level**: Low (templates only, no data loss)
**Rollback**: Easy (reinstall previous version)

---

## Support

### Quick Reference

**New Command Format**: `/sdlc:{main-command}-{subcommand}`

Examples:
- `/sdlc:prd-generate "description"`
- `/sdlc:task-start TASK-001`
- `/sdlc:task-complete TASK-001`

### Getting Help

If you encounter issues:

1. **Check installation**:
   ```bash
   a-sdlc install --list
   ```

2. **Verify templates**:
   ```bash
   cat ~/.claude/commands/sdlc/prd.md | grep "/sdlc:prd-"
   ```

3. **File an issue**:
   Report problems at the project repository

---

## Next Steps

1. ✅ Run `a-sdlc install --force`
2. ✅ Test commands in Claude Code
3. ✅ Update any documentation or scripts that reference old commands
4. ✅ Share feedback on the new naming convention

---

## Benefits You'll Experience

After deployment:

✅ **Faster command discovery**: Autocomplete shows logical groups
✅ **Less confusion**: Clear distinction between command and subcommand
✅ **Professional experience**: Matches industry-standard CLI patterns
✅ **Better documentation**: Commands are self-describing

---

## Questions?

**Q: Will old commands still work?**
A: No, you must use the new hyphenated format after deployment.

**Q: Do I need to update my PRDs or tasks?**
A: No, your data files (`.sdlc/prds/`, `.sdlc/tasks/`) are unchanged.

**Q: Can I keep using the old format?**
A: No, the old space-based format is deprecated.

**Q: How often should I run `a-sdlc install`?**
A: Whenever you update the a-sdlc package or want the latest templates.

---

## Deployment Checklist

- [ ] Run `a-sdlc install --force`
- [ ] Verify PRD commands work (`/sdlc:prd-list`)
- [ ] Verify task commands work (`/sdlc:task-list`)
- [ ] Check autocomplete shows hyphenated commands
- [ ] Update any local documentation or notes
- [ ] Test common workflows end-to-end

**Status**: Ready to deploy ✅

---

**Last Updated**: 2026-01-22
**Version**: 1.0
