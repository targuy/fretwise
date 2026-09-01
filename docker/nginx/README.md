# Reverse proxy UGREEN

Endpoint principal : `https://fretwise.familleguitard.fr`.

Endpoint LAN de secours : `https://fretwise.mblanche.direct.ug.link`.

## Contrat

- Technitium héberge zone primaire locale exacte `fretwise.mblanche.direct.ug.link` avec
  enregistrement A `192.168.1.50`, TTL 300.
- Nginx UGOS termine TLS avec certificat wildcard ZeroSSL géré par UGREEN.
- Backend FretWise écoute seulement `127.0.0.1:8080`.
- Le service `cloudflared` du Compose publie endpoint principal via tunnel sortant.
- Jeton tunnel : `/volume2/docker/fretwise/shared/cloudflared.token`, propriétaire
  `root:65532`, mode `0640`, jamais versionné ni placé dans fichier d'environnement
  applicatif.
- Illustrations pédales non versionnées : `/volume2/docker/fretwise/state/pedals`,
  monté en lecture seule dans `/app/data/pedals`.
- `/volume2/docker/fretwise/proxy/fretwise-ugreen.conf` est source persistante.
- drop-in `/etc/systemd/system/nginx.service.d/fretwise.conf` restaure bloc après reset UGOS.

## Validation

```sh
sudo nginx -t
systemctl restart nginx
curl -fsS https://fretwise.mblanche.direct.ug.link/health/ready
curl -fsS https://fretwise.familleguitard.fr/health/ready
sudo docker ps --filter name=fretwise-web-1
sudo docker ps --filter name=fretwise-cloudflared-1
```

## Rollback proxy

```sh
sudo rm -f /etc/systemd/system/nginx.service.d/fretwise.conf
sudo rm -f /etc/nginx/server.d/fretwise.conf
sudo systemctl daemon-reload
sudo nginx -t
sudo systemctl reload nginx
```

Supprimer ensuite zone Technitium exacte via API/UI si endpoint est définitivement retiré.
Ne pas supprimer zones `familleguitard.fr` ou reverse LAN.
