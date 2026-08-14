# Working agreement — Sysible Workstation

## 🚫 NEVER build an ISO unless explicitly told to — HARD RULE
Do **NOT** trigger an ISO build under any circumstances unless the user, in that same
message, explicitly tells you to build / kick / cut / rebuild an ISO. This includes:
- running the `iso.yml` workflow (`actions_run_trigger` / `run_workflow`),
- `workflow_dispatch` of the ISO build, or any equivalent.

Committing and pushing changes is fine. **Building the ISO is not** — wait to be told.
If you think an ISO is needed, *ask first and stop*. Do not infer permission from "test
it", "make a release", or prior builds. When in doubt, do not build.

## Preferred workflow for boot / desktop cosmetics
1. **Lock the look with mockups FIRST.** Render the GRUB theme / Plymouth splash / wallpaper
   with PIL at the resolution they actually render (the GRUB menu + Plymouth come up at
   **1024×768**, not the panel's native res) and get the user's sign-off *before* any build.
2. Boot branding (GRUB theme in `boot/grub/themes/sysible`, Plymouth in
   `usr/share/plymouth/themes/sysible`) is baked into the ISO `includes.chroot` — it can only
   be *seen* by booting a built ISO, so getting it right on paper first avoids wasted builds.
3. **Batch** all pending visual changes into ONE ISO at the very end — never one ISO per tweak.
4. Desktop bits that live in packages (`sysible-desktop-gnome`, `sysible-artwork`) can be
   delivered to a running system via `apt upgrade` from the published repo — no ISO needed.
