CREATE SCHEMA IF NOT EXISTS trucks;

CREATE TABLE IF NOT EXISTS trucks.integration_jobs (
    job_name text PRIMARY KEY,
    request_type text NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    interval_seconds integer NOT NULL,
    next_run_at timestamptz NOT NULL DEFAULT now(),
    last_success_at timestamptz,
    last_error_at timestamptz,
    last_error_message text,
    last_status text,
    last_records_inserted integer NOT NULL DEFAULT 0,
    last_records_ignored integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS trucks.integration_errors (
    id bigserial PRIMARY KEY,
    job_name text,
    stage text NOT NULL,
    error_message text,
    source_hash text,
    occurred_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS trucks.veiculos (
    id bigserial PRIMARY KEY,
    veiculo_id bigint NOT NULL,
    placa text,
    versao_comp_bordo numeric(10,2),
    sensor_temp1 boolean,
    sensor_temp2 boolean,
    sensor_temp3 boolean,
    tempo_reenvio_comando integer,
    teclado_macro boolean,
    permissao_envio_comando boolean,
    temporizador_padrao integer,
    temporizador_satelital_atual integer,
    tipo_equipamento integer,
    nome_motorista text,
    proprietario boolean,
    direito_inteligencia_embarcada boolean,
    inteligencia_embarcada boolean,
    localizador boolean,
    identificacao_equipamento text,
    manutencao boolean,
    data_expiracao_espelhamento timestamptz,
    direito_cancelar_espelhamento boolean,
    permissao_compartilhar boolean,
    temporizador_gsm integer,
    permissao_alterar_pos_satelital boolean,
    temporizador_pos_parado integer,
    temporizador_pos_parado_menor_60 integer,
    chassi text,
    ultima_manutencao_at timestamptz,
    source_hash text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE trucks.veiculos
ADD COLUMN IF NOT EXISTS source_hash text;

ALTER TABLE trucks.veiculos
ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();

ALTER TABLE trucks.veiculos
ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

CREATE UNIQUE INDEX IF NOT EXISTS ux_veiculos_veiculo_id
ON trucks.veiculos (veiculo_id);

CREATE INDEX IF NOT EXISTS idx_veiculos_placa
ON trucks.veiculos (placa);

CREATE TABLE IF NOT EXISTS trucks.motoristas (
    id bigserial PRIMARY KEY,
    name text NOT NULL,
    cpf text,
    rg text,
    birth_date date,
    phone text,
    email text,
    cnh_number text,
    cnh_category text,
    cnh_expires_at date,
    mopp_expires_at date,
    admission_date date,
    contract_type text,
    registration_number text,
    status text NOT NULL DEFAULT 'ativo',
    assigned_vehicle_plate text,
    base text,
    address text,
    emergency_contact_name text,
    emergency_contact_phone text,
    notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_motoristas_cpf
ON trucks.motoristas (cpf)
WHERE cpf IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_motoristas_name
ON trucks.motoristas (name);

CREATE INDEX IF NOT EXISTS idx_motoristas_status
ON trucks.motoristas (status);

CREATE TABLE IF NOT EXISTS trucks.mensagens_cb (
    id bigserial PRIMARY KEY,
    mensagem_id bigint NOT NULL,
    veiculo_id bigint,
    data_hora timestamptz NOT NULL,
    latitude numeric(10,7),
    longitude numeric(10,7),
    municipio text,
    uf char(2),
    rodovia text,
    rua text,
    velocidade integer,
    evt2_sirene_acionada boolean,
    evt3_veiculo_bloqueado boolean,
    evt4_ignicao_acionada boolean,
    evt12_porta_carona_aberta boolean,
    evt13_porta_motorista_aberta boolean,
    origem_mensagem integer,
    tipo_mensagem integer,
    data_hora_inclusao timestamptz,
    odometro bigint,
    bateria_carreta numeric(10,2),
    rpm integer,
    evt27_desengate_carreta2 boolean,
    evento_gerador integer,
    alerta_telemetria text,
    source_hash text,
    created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE trucks.mensagens_cb
ADD COLUMN IF NOT EXISTS source_hash text;

ALTER TABLE trucks.mensagens_cb
ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();

CREATE UNIQUE INDEX IF NOT EXISTS ux_mensagens_cb_mensagem_id
ON trucks.mensagens_cb (mensagem_id);

CREATE INDEX IF NOT EXISTS idx_mensagens_cb_veiculo_data
ON trucks.mensagens_cb (veiculo_id, data_hora DESC);

CREATE INDEX IF NOT EXISTS idx_mensagens_cb_data
ON trucks.mensagens_cb (data_hora DESC);

CREATE TABLE IF NOT EXISTS trucks.ocorrencias_telemetria (
    id bigserial PRIMARY KEY,
    veiculo_id bigint NOT NULL,
    data_hora timestamptz NOT NULL,
    velocidade integer,
    rpm integer,
    velocidade_max integer,
    porcentagem_tanque numeric(8,3),
    source_hash text,
    created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE trucks.ocorrencias_telemetria
ADD COLUMN IF NOT EXISTS source_hash text;

ALTER TABLE trucks.ocorrencias_telemetria
ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();

CREATE UNIQUE INDEX IF NOT EXISTS ux_ocorrencias_telemetria_natural
ON trucks.ocorrencias_telemetria (
    veiculo_id,
    data_hora,
    velocidade,
    rpm,
    velocidade_max,
    porcentagem_tanque
);

CREATE INDEX IF NOT EXISTS idx_ocorrencias_veiculo_data
ON trucks.ocorrencias_telemetria (veiculo_id, data_hora DESC);

CREATE TABLE IF NOT EXISTS trucks.telemetria_relatorio (
    id bigserial PRIMARY KEY,
    veiculo_id bigint NOT NULL,
    data_referencia date NOT NULL,
    distancia integer,
    velocidade_media integer,
    velocidade_max integer,
    hora_ini integer,
    hora_fim integer,
    utilizacao integer,
    hodometro_ini bigint,
    hodometro_fim bigint,
    media_consumo numeric(12,6),
    consumo_hora_motor numeric(12,6),
    rpm_medio integer,
    rpm_max integer,
    temperatura_media integer,
    total_motor_lig interval,
    total_motor_deslig interval,
    total_motor_lig_mov interval,
    total_motor_lig_par interval,
    source_hash text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE trucks.telemetria_relatorio
ADD COLUMN IF NOT EXISTS source_hash text;

ALTER TABLE trucks.telemetria_relatorio
ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();

ALTER TABLE trucks.telemetria_relatorio
ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

CREATE UNIQUE INDEX IF NOT EXISTS ux_telemetria_relatorio_veiculo_data
ON trucks.telemetria_relatorio (veiculo_id, data_referencia);

CREATE INDEX IF NOT EXISTS idx_telemetria_relatorio_data
ON trucks.telemetria_relatorio (data_referencia DESC);

CREATE TABLE IF NOT EXISTS trucks.veiculos_temp (
    id bigserial PRIMARY KEY,
    source_hash text NOT NULL UNIQUE,
    requested_at timestamptz NOT NULL DEFAULT now(),
    http_status integer,
    payload text NOT NULL,
    payload_size integer NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    attempts integer NOT NULL DEFAULT 0,
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_veiculos_temp_status
ON trucks.veiculos_temp (status, created_at);

CREATE TABLE IF NOT EXISTS trucks.veiculos_importados (
    id bigserial PRIMARY KEY,
    source_hash text NOT NULL UNIQUE,
    requested_at timestamptz,
    imported_at timestamptz NOT NULL DEFAULT now(),
    http_status integer,
    payload text NOT NULL,
    payload_size integer NOT NULL,
    records_read integer NOT NULL DEFAULT 0,
    records_inserted integer NOT NULL DEFAULT 0,
    records_ignored integer NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS trucks.mensagens_cb_temp (
    id bigserial PRIMARY KEY,
    source_hash text NOT NULL UNIQUE,
    requested_at timestamptz NOT NULL DEFAULT now(),
    http_status integer,
    payload text NOT NULL,
    payload_size integer NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    attempts integer NOT NULL DEFAULT 0,
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mensagens_cb_temp_status
ON trucks.mensagens_cb_temp (status, created_at);

CREATE TABLE IF NOT EXISTS trucks.mensagens_cb_importados (
    id bigserial PRIMARY KEY,
    source_hash text NOT NULL UNIQUE,
    requested_at timestamptz,
    imported_at timestamptz NOT NULL DEFAULT now(),
    http_status integer,
    payload text NOT NULL,
    payload_size integer NOT NULL,
    records_read integer NOT NULL DEFAULT 0,
    records_inserted integer NOT NULL DEFAULT 0,
    records_ignored integer NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS trucks.ocorrencias_telemetria_temp (
    id bigserial PRIMARY KEY,
    source_hash text NOT NULL UNIQUE,
    requested_at timestamptz NOT NULL DEFAULT now(),
    http_status integer,
    payload text NOT NULL,
    payload_size integer NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    attempts integer NOT NULL DEFAULT 0,
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ocorrencias_telemetria_temp_status
ON trucks.ocorrencias_telemetria_temp (status, created_at);

CREATE TABLE IF NOT EXISTS trucks.ocorrencias_telemetria_importados (
    id bigserial PRIMARY KEY,
    source_hash text NOT NULL UNIQUE,
    requested_at timestamptz,
    imported_at timestamptz NOT NULL DEFAULT now(),
    http_status integer,
    payload text NOT NULL,
    payload_size integer NOT NULL,
    records_read integer NOT NULL DEFAULT 0,
    records_inserted integer NOT NULL DEFAULT 0,
    records_ignored integer NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS trucks.telemetria_relatorio_temp (
    id bigserial PRIMARY KEY,
    source_hash text NOT NULL UNIQUE,
    requested_at timestamptz NOT NULL DEFAULT now(),
    http_status integer,
    payload text NOT NULL,
    payload_size integer NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    attempts integer NOT NULL DEFAULT 0,
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_telemetria_relatorio_temp_status
ON trucks.telemetria_relatorio_temp (status, created_at);

CREATE TABLE IF NOT EXISTS trucks.telemetria_relatorio_importados (
    id bigserial PRIMARY KEY,
    source_hash text NOT NULL UNIQUE,
    requested_at timestamptz,
    imported_at timestamptz NOT NULL DEFAULT now(),
    http_status integer,
    payload text NOT NULL,
    payload_size integer NOT NULL,
    records_read integer NOT NULL DEFAULT 0,
    records_inserted integer NOT NULL DEFAULT 0,
    records_ignored integer NOT NULL DEFAULT 0
);
