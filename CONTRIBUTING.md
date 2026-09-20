# Workflow de contribution — VoxCPM Studio

Le dépôt ne reçoit les changements que par **pull request** : `main` reste la
branche de référence (CI Windows obligatoire), le travail se fait sur une
branche de fonctionnalité.

```bash
git checkout -b feat/ma-fonctionnalite   # depuis main
# … travail, commits …
git push -u origin feat/ma-fonctionnalite
gh pr create --base main --title "…" --body "…"
```

La description de la PR est pré-remplie par le gabarit
[`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md)
(intention, preuves, limites connues).

## Règles

1. **Base toujours `main`**, une intention par PR (pas de PR fourre-tout).
2. Le titre suit le style des commits existants (une phrase, impératif).
3. La CI `.github/workflows/windows.yml` (build `.exe` + smoke test) doit être
   verte avant fusion — c'est la seule preuve d'exécution du binaire Windows.
4. Ne jamais commiter : poids GGUF, sources/binaire `gguf/`, `outputs/`,
   `refs/`, build — le `.gitignore` les filtre déjà.
