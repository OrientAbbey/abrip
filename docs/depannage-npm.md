# Dépannage — `npm install` échoue avec `getaddrinfo ENOENT registry.npmjs.org`

## Ce que dit le journal

Le journal fourni (`2026-09-19T22_34_33_269Z-debug-0.log`) montre que `npm install` a
d'abord téléchargé la quasi-totalité des paquets depuis le cache local, puis a
échoué à la toute fin :

```
344 verbose stack FetchError: request to https://registry.npmjs.org/vite/-/vite-5.4.21.tgz
    failed, reason: getaddrinfo ENOENT registry.npmjs.org
345 error code ENOENT
346 error syscall getaddrinfo
```

`getaddrinfo ENOENT` est une erreur de **résolution DNS** : à cet instant précis,
Windows n'a pas réussi à traduire `registry.npmjs.org` en adresse IP. Ce n'est
pas une erreur du projet ni de son `package.json` — la preuve en est que le
journal liste par ailleurs les dépendances réelles de Recharts 3
(`@reduxjs/toolkit`, `react-redux`, `redux-thunk` en font partie depuis que
Recharts a réécrit sa gestion d'état interne avec Redux Toolkit) : le contenu
attendu par le projet est correct, seul le réseau a lâché en cours de route.

## Causes possibles, par ordre de fréquence

1. **Coupure ou instabilité de la connexion internet** au moment précis de
   l'installation — la cause la plus fréquente sur une connexion mobile ou peu
   stable.
2. **Serveur DNS du fournisseur d'accès temporairement indisponible.**
3. **VPN, proxy d'entreprise ou pare-feu/antivirus** interceptant ou bloquant
   la résolution de `registry.npmjs.org`.
4. **Cache npm partiellement corrompu** — le journal contient plusieurs lignes
   `seems to be corrupted. Trying again.` juste avant l'échec final, signe que
   quelques tarballs en cache étaient déjà abîmés.

## Correction

Le dépôt inclut désormais `frontend/.npmrc`, qui augmente le nombre de
tentatives et les délais d'attente — cela suffit à absorber une micro-coupure
sans faire échouer toute l'installation. Si l'erreur se reproduit malgré tout :

```powershell
# 1. Vérifier que la connexion fonctionne et que le DNS résout bien
ping registry.npmjs.org

# 2. Si la résolution échoue, vider le cache DNS de Windows
ipconfig /flushdns

# 3. Nettoyer un cache npm potentiellement corrompu
npm cache clean --force

# 4. Repartir d'un état propre
cd frontend
rmdir /s /q node_modules
del package-lock.json
npm install
```

Si le problème persiste uniquement sur ce réseau (bureau, universität,
entreprise), c'est le signe d'un VPN ou d'un pare-feu qui filtre le trafic vers
`registry.npmjs.org` : essayer depuis un autre réseau (partage de connexion
mobile) confirme le diagnostic en quelques secondes.

## Ce n'est pas un problème de version des paquets

`package.json` et `package-lock.json` sont corrects et inchangés par cette
note : `recharts@^3.10.1` avec ses dépendances réelles (y compris la famille
Redux). Aucune modification du code n'était nécessaire ici — uniquement une
installation plus tolérante aux à-coups réseau.
