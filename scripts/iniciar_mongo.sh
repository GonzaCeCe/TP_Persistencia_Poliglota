#!/bin/sh
set -e

mongo_sh() {
    mongosh --quiet --host mongo --port "$MONGO_PORT" "$@"
}

mongo_sh --eval "try { rs.status().ok } catch (e) { rs.initiate({_id: '$MONGO_REPLICA_SET', members: [{_id: 0, host: 'localhost:$MONGO_PORT'}]}).ok }"
for intento in $(seq 1 30); do
    if [ "$(mongo_sh --eval 'db.hello().isWritablePrimary')" = "true" ]; then
        mongo_sh "$MONGO_DB" --file /scripts/mongo_init.js
        exit 0
    fi
    sleep 1
done
echo "El replica set de MongoDB no eligio primario" >&2
exit 1
