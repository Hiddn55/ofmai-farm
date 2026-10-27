#!/bin/sh
# Exporte les secrets de la ferme du Trousseau de CE Mac vers un script à rejouer
# sur le Mac mini (iCloud ne synchronise pas les entrées `security add-generic-password`).
#
#   sh scripts/keychain-export.sh            # écrit ~/Desktop/ofmai-farm-keychain-<date>.sh (chmod 600)
#   # AirDrop le fichier sur le Mac mini, puis là-bas :
#   sh ~/Desktop/ofmai-farm-keychain-<date>.sh && rm ~/Desktop/ofmai-farm-keychain-<date>.sh
#
# Rien n'est affiché à l'écran. Le fichier contient les mots de passe en clair :
# il se supprime des deux côtés une fois rejoué.
set -eu
out="$HOME/Desktop/ofmai-farm-keychain-$(date +%Y%m%d).sh"
: > "$out"
chmod 600 "$out"
printf '#!/bin/sh\nset -e\n' >> "$out"
n=0
for svc in $(security dump-keychain 2>/dev/null | /usr/bin/grep -oE '"svce"<blob>="(geelark-api-key|ofmai-anthropic-key|ofmai-discord-webhook|ofmai-farm-[^"]+|ofmai-social-[^"]+)"' | sed 's/.*="\(.*\)"/\1/' | sort -u); do
  acct=$(security find-generic-password -s "$svc" 2>/dev/null | /usr/bin/grep '"acct"' | sed 's/.*<blob>="\(.*\)"/\1/' || true)
  pw=$(security find-generic-password -s "$svc" -w 2>/dev/null || true)
  [ -z "$pw" ] && continue
  esc_pw=$(printf '%s' "$pw" | sed "s/'/'\\\\''/g")
  esc_acct=$(printf '%s' "${acct:-$svc}" | sed "s/'/'\\\\''/g")
  printf "security add-generic-password -s '%s' -a '%s' -w '%s' -U\n" "$svc" "$esc_acct" "$esc_pw" >> "$out"
  n=$((n + 1))
done
printf 'echo "%s entrées importées"\n' "$n" >> "$out"
echo "$n entrées écrites dans $out (aucune affichée). AirDrop → Mac mini → sh <fichier> → rm des deux côtés."
