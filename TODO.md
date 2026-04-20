# Active TODO

## Rename: manual steps remaining

- [ ] Rename repo on Gitea (`git.thelunadog.com:alex/MyAgent` → `alex/MyDevTeam`)
- [ ] Update git remote: `git remote set-url origin git@git.thelunadog.com:alex/MyDevTeam.git`
- [ ] Rename directory: `mv ~/projects/MyAgent ~/projects/MyDevTeam`
- [ ] Update `.env` if `MAC_AGENT_API_KEY` is set → `MYDEVTEAM_API_KEY`
- [ ] Rebuild Docker container: `docker compose down && docker compose up -d`
- [ ] Check `../MyWeb` for any MyAgent references

## Mail engine redesign

- [ ] Execute implementation plan (`docs/superpowers/plans/2026-04-19-mail-engine.md`)
- Spec and plan ready, not yet implemented
