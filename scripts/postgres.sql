-- Creacion del modelo relacional. Idempotente: se puede ejecutar mas de una vez.

CREATE TABLE IF NOT EXISTS rol (
    id              SMALLINT PRIMARY KEY,
    descripcion     VARCHAR(20) NOT NULL UNIQUE,
    nivel_permisos  SMALLINT NOT NULL CHECK (nivel_permisos BETWEEN 1 AND 5)
);

INSERT INTO rol (id, descripcion, nivel_permisos) VALUES
    (1, 'ADMIN', 5),
    (2, 'OPERADOR', 3),
    (3, 'CLIENTE', 1)
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS cliente (
    id            INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    razon_social  VARCHAR(150) NOT NULL,
    cuit          CHAR(13) NOT NULL UNIQUE CHECK (cuit ~ '^\d{2}-\d{8}-\d$'),
    email         VARCHAR(150) NOT NULL CHECK (email LIKE '%_@_%'),
    telefono      VARCHAR(30),
    direccion     VARCHAR(200),
    pais          CHAR(2) NOT NULL CHECK (pais ~ '^[A-Z]{2}$'),
    estado        VARCHAR(10) NOT NULL DEFAULT 'ACTIVO'
                  CHECK (estado IN ('ACTIVO', 'INACTIVO', 'BAJA'))
);

CREATE TABLE IF NOT EXISTS empresa (
    id            INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tipo          VARCHAR(10) NOT NULL CHECK (tipo IN ('OPERADOR', 'PROVEEDOR')),
    razon_social  VARCHAR(150) NOT NULL,
    cuit          CHAR(13) NOT NULL UNIQUE CHECK (cuit ~ '^\d{2}-\d{8}-\d$'),
    pais          CHAR(2) NOT NULL CHECK (pais ~ '^[A-Z]{2}$'),
    estado        VARCHAR(10) NOT NULL DEFAULT 'ACTIVO'
                  CHECK (estado IN ('ACTIVO', 'INACTIVO', 'BAJA'))
);

CREATE TABLE IF NOT EXISTS usuario (
    id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cliente_id      INTEGER REFERENCES cliente (id),
    nombre          VARCHAR(80) NOT NULL,
    apellido        VARCHAR(80) NOT NULL,
    email           VARCHAR(150) NOT NULL UNIQUE CHECK (email LIKE '%_@_%' AND email = lower(email)),
    password_hash   CHAR(60) NOT NULL,
    estado          VARCHAR(10) NOT NULL DEFAULT 'ACTIVO'
                    CHECK (estado IN ('ACTIVO', 'BLOQUEADO', 'BAJA')),
    fecha_registro  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS usuario_rol (
    usuario_id  INTEGER NOT NULL REFERENCES usuario (id),
    rol_id      SMALLINT NOT NULL REFERENCES rol (id),
    PRIMARY KEY (usuario_id, rol_id)
);

CREATE TABLE IF NOT EXISTS sesion (
    id            UUID PRIMARY KEY,
    usuario_id    INTEGER NOT NULL REFERENCES usuario (id),
    fecha_inicio  TIMESTAMPTZ NOT NULL,
    fecha_fin     TIMESTAMPTZ,
    estado        VARCHAR(10) NOT NULL CHECK (estado IN ('ACTIVA', 'CERRADA', 'EXPIRADA')),
    CHECK (fecha_fin >= fecha_inicio),
    CHECK ((estado = 'ACTIVA') = (fecha_fin IS NULL))
);

CREATE INDEX IF NOT EXISTS ix_sesion_activa_usuario ON sesion (usuario_id) WHERE estado = 'ACTIVA';

CREATE TABLE IF NOT EXISTS contenedor (
    id                    INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    codigo_internacional  CHAR(11) NOT NULL UNIQUE CHECK (codigo_internacional ~ '^[A-Z]{4}\d{7}$'),
    tipo                  VARCHAR(10) NOT NULL CHECK (tipo IN ('DRY', 'REEFER', 'TANK', 'OPEN_TOP')),
    capacidad_m3          NUMERIC(8, 2) NOT NULL CHECK (capacidad_m3 > 0),
    temp_min              NUMERIC(5, 2) NOT NULL,
    temp_max              NUMERIC(5, 2) NOT NULL,
    estado                VARCHAR(15) NOT NULL DEFAULT 'DISPONIBLE'
                          CHECK (estado IN ('DISPONIBLE', 'EN_USO', 'MANTENIMIENTO', 'BAJA')),
    CHECK (temp_min < temp_max)
);

CREATE TABLE IF NOT EXISTS sensor (
    id                 INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tipo               VARCHAR(12) NOT NULL
                       CHECK (tipo IN ('TEMPERATURA', 'HUMEDAD', 'VIBRACION', 'GPS', 'MULTI')),
    fabricante         VARCHAR(80) NOT NULL,
    fecha_instalacion  TIMESTAMPTZ NOT NULL,
    estado             VARCHAR(10) NOT NULL DEFAULT 'ACTIVO'
                       CHECK (estado IN ('ACTIVO', 'INACTIVO', 'FALLA', 'BAJA')),
    contenedor_id      INTEGER REFERENCES contenedor (id)
);

CREATE TABLE IF NOT EXISTS vehiculo (
    id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tipo            VARCHAR(10) NOT NULL CHECK (tipo IN ('CAMION', 'TREN', 'BUQUE', 'AVION')),
    identificacion  VARCHAR(30) NOT NULL UNIQUE,
    empresa_id      INTEGER NOT NULL REFERENCES empresa (id),
    estado          VARCHAR(15) NOT NULL DEFAULT 'ACTIVO'
                    CHECK (estado IN ('ACTIVO', 'INACTIVO', 'MANTENIMIENTO', 'BAJA'))
);

CREATE TABLE IF NOT EXISTS cuenta_corriente (
    id                   INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cliente_id           INTEGER UNIQUE REFERENCES cliente (id),
    empresa_id           INTEGER UNIQUE REFERENCES empresa (id),
    saldo                NUMERIC(14, 2) NOT NULL DEFAULT 0,
    fecha_actualizacion  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (num_nonnulls(cliente_id, empresa_id) = 1)
);

CREATE TABLE IF NOT EXISTS factura (
    id             INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cliente_id     INTEGER NOT NULL REFERENCES cliente (id),
    periodo        CHAR(7) NOT NULL CHECK (periodo ~ '^\d{4}-(0[1-9]|1[0-2])$'),
    fecha_emision  DATE NOT NULL,
    importe_total  NUMERIC(14, 2) NOT NULL CHECK (importe_total > 0),
    estado         VARCHAR(15) NOT NULL DEFAULT 'EMITIDA'
                   CHECK (estado IN ('EMITIDA', 'PAGADA_PARCIAL', 'PAGADA', 'ANULADA'))
);

CREATE INDEX IF NOT EXISTS ix_factura_cliente ON factura (cliente_id, fecha_emision);

CREATE TABLE IF NOT EXISTS factura_item (
    id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    factura_id  INTEGER NOT NULL REFERENCES factura (id),
    envio_id    INTEGER NOT NULL UNIQUE,
    importe     NUMERIC(14, 2) NOT NULL CHECK (importe > 0)
);

CREATE INDEX IF NOT EXISTS ix_factura_item_factura ON factura_item (factura_id);

CREATE TABLE IF NOT EXISTS pago (
    id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    factura_id  INTEGER NOT NULL REFERENCES factura (id),
    fecha       DATE NOT NULL,
    monto       NUMERIC(14, 2) NOT NULL CHECK (monto > 0),
    medio_pago  VARCHAR(15) NOT NULL
                CHECK (medio_pago IN ('TRANSFERENCIA', 'TARJETA', 'CHEQUE', 'EFECTIVO'))
);

CREATE INDEX IF NOT EXISTS ix_pago_factura ON pago (factura_id);

CREATE TABLE IF NOT EXISTS movimiento_cc (
    id           INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cuenta_id    INTEGER NOT NULL REFERENCES cuenta_corriente (id),
    fecha        DATE NOT NULL,
    tipo         VARCHAR(5) NOT NULL CHECK (tipo IN ('DEBE', 'HABER')),
    importe      NUMERIC(14, 2) NOT NULL CHECK (importe > 0),
    factura_id   INTEGER REFERENCES factura (id),
    pago_id      INTEGER REFERENCES pago (id),
    envio_id     INTEGER,
    descripcion  VARCHAR(200) NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_movimiento_cuenta_fecha ON movimiento_cc (cuenta_id, fecha);
CREATE UNIQUE INDEX IF NOT EXISTS ux_movimiento_cuenta_envio ON movimiento_cc (cuenta_id, envio_id)
    WHERE envio_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS cierre_cc (
    cuenta_id      INTEGER NOT NULL REFERENCES cuenta_corriente (id),
    periodo        CHAR(7) NOT NULL CHECK (periodo ~ '^\d{4}-(0[1-9]|1[0-2])$'),
    saldo_inicial  NUMERIC(14, 2) NOT NULL,
    total_debe     NUMERIC(14, 2) NOT NULL CHECK (total_debe >= 0),
    total_haber    NUMERIC(14, 2) NOT NULL CHECK (total_haber >= 0),
    saldo_final    NUMERIC(14, 2) NOT NULL,
    PRIMARY KEY (cuenta_id, periodo),
    CHECK (saldo_final = saldo_inicial + total_debe - total_haber)
);
