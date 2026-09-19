# Workflow PR — VoxCPM Studio

Le dépôt ne reçoit les changements que par **pull request** : `main` reste la
branche de référence (CI Windows obligatoire), le travail se fait sur une
branche de fonctionnalité.

## Ouvrir une PR (après `gh auth login`, une seule fois)

```bash
git checkout -b feat/ma-fonctionnalité   # depuis main
# … travail, commits …
git push -u origin feat/ma-fonctionnalité
gh pr create --base main --title "…" --body "…"
```

## Gabarit de description

```markdown
## Intention
Pourquoi ce changement (le « pourquoi », pas le « quoi »).

## Ce qui est prouvé
- [ ] Build/tests exécutés localement (py_compile + flux API concernés)
- [ ] CI Windows verte : https://github.com/<propriétaire>/VoxCPM-Studio/actions
- [ ] Interface testée si l'UI est touchée

## Limites connues
Ce qui reste non testé et pourquoi (ex. : uniquement vérifiable sur un PC).
```

## Règles

1. **Base toujours `main`**, une intention par PR (pas de PR fourre-tout).
2. Le titre suit le style des commits existants (une phrase, impératif).
3. La CI `.github/workflows/windows.yml` (build `.exe` + smoke test) doit être
   verte avant fusion — c'est la seule preuve d'exécution du binaire Windows.
4. Ne jamais commiter : poids GGUF, sources/binaire `gguf/`, `outputs/`,
   `refs/`, build — le `.gitignore` les filtre déjà.
