# Web client dependency notes

## Next.js version

CLAUDE.md specifies Next.js 15. Pinned to **15.5.25**, the latest patched 15.x
release, rather than the 15.1.6 originally scaffolded, which npm flags for
CVE-2025-66478.

## Accepted risk: bundled postcss

`npm audit` reports two advisories after that upgrade:

| Package | Severity | Issue |
| --- | --- | --- |
| postcss (bundled in next) | high | Path traversal and arbitrary `.map` file disclosure via attacker-controlled `sourceMappingURL` in CSS comments |
| next | moderate | Inherits the above through its bundled copy |

**Not fixed.** The only remedy npm offers is Next.js 16, a major version bump
away from the version this project specifies.

**Why this is accepted:**

- Both flaws are in **build-time** CSS processing, not the runtime server.
- Exploiting them requires the attacker to control CSS source fed to the
  bundler. All CSS here is written by the project and committed to the repo;
  no user input reaches PostCSS.
- The disclosure target is `.map` files on the build machine, which for this
  project is a developer laptop, not a shared build server.

**Revisit if:** the project ever accepts user-supplied CSS or themes, or builds
in a shared CI environment where the source tree is not fully trusted.

Recorded here and in `docs/security-review.md` so the decision is visible
rather than implied by silence.
