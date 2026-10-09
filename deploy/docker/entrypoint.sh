#!/bin/sh
# Pterodactyl mounts its server volume over /home/container, so the code lives
# in /app and we always run from there.
cd /app || exit 1

# Under Pterodactyl, Wings passes the egg's startup line in $STARTUP with
# {{VAR}} placeholders; expand them to ${VAR} and run it.
if [ -n "${STARTUP}" ]; then
    MODIFIED_STARTUP=$(echo "${STARTUP}" | sed -e 's/{{/${/g' -e 's/}}/}/g')
    echo ":/app$ ${MODIFIED_STARTUP}"
    eval "exec ${MODIFIED_STARTUP}"
fi

exec "$@"
