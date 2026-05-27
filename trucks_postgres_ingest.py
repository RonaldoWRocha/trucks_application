import argparse
import hashlib
import io
import os
import time
import zipfile
from dotenv import load_dotenv
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree import ElementTree as ET

load_dotenv()

POSTGRES_DSN = os.getenv("POSTGRES_DSN")
APP_ENCRYPTION_KEY = os.getenv("APP_ENCRYPTION_KEY")

JOBS = {
    "veiculos": {
        "request_type": "RequestVeiculo",
        "interval_seconds": int(os.getenv("TRUCKS_VEICULOS_INTERVAL", "86400")),
        "additional_xml": "",
    },
    "telemetria_relatorio": {
        "request_type": "RequestTelemetriaRelatorio",
        "interval_seconds": int(os.getenv("TRUCKS_TELEMETRIA_RELATORIO_INTERVAL", "300")),
        "additional_xml": f"<tID>{os.getenv('TRUCKS_TELEMETRIA_TID', '1')}</tID>",
    },
    "mensagens_cb": {
        "request_type": "RequestMensagemCB",
        "interval_seconds": int(os.getenv("TRUCKS_MENSAGENS_INTERVAL", "60")),
        "additional_xml": f"<mId>{os.getenv('TRUCKS_MENSAGEM_MID', '148725040945')}</mId>",
    },
    "ocorrencias_telemetria": {
        "request_type": "RequestTelemetriaOcorrencias",
        "interval_seconds": int(os.getenv("TRUCKS_OCORRENCIAS_INTERVAL", "86400")),
        "additional_xml": "",
    },
}

def require_env(include_api=True) -> None:
    required = {"POSTGRES_DSN": POSTGRES_DSN}
    if include_api:
        required.update({"APP_ENCRYPTION_KEY": APP_ENCRYPTION_KEY})
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError(f"Variaveis de ambiente ausentes: {', '.join(missing)}")


def connect(include_api=True):
    require_env(include_api=include_api)
    import psycopg

    return psycopg.connect(POSTGRES_DSN)


def quote_ident(value):
    import re

    if not re.match(r"^[a-z][a-z0-9_]*$", value or ""):
        raise RuntimeError(f"Schema invalido: {value}")
    return f'"{value}"'


def active_clients(conn, only_client=None):
    with conn.cursor() as cur:
        params = []
        where = ["c.enabled = true", "ic.enabled = true", "ic.provider = 'trucks'"]
        if only_client:
            params.append(only_client)
            where.append("(c.slug = %s or c.schema_name = %s)")
            params.append(only_client)
        cur.execute(
            f"""
            SELECT
                c.id,
                c.name,
                c.slug,
                c.schema_name,
                ic.api_url,
                ic.login,
                pgp_sym_decrypt(decode(ic.password_encrypted, 'base64'), %s) as password
            FROM public.clients c
            JOIN public.integration_credentials ic ON ic.client_id = c.id
            WHERE {' AND '.join(where)}
            ORDER BY c.id
            """,
            [APP_ENCRYPTION_KEY, *params],
        )
        return [
            {
                "id": row[0],
                "name": row[1],
                "slug": row[2],
                "schema_name": row[3],
                "schema": quote_ident(row[3]),
                "api_url": row[4],
                "login": row[5],
                "password": row[6],
            }
            for row in cur.fetchall()
        ]


def text_of(node, tag):
    child = node.find(tag)
    if child is None or child.text is None:
        return None
    value = child.text.strip()
    return value if value != "" else None


def to_int(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def to_decimal(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", "."))
    except InvalidOperation:
        return None


def to_bool(value):
    if value is None:
        return None
    return str(value).strip().lower() in {"1", "true", "s", "sim", "yes"}


def to_datetime(value):
    if value in (None, ""):
        return None
    value = value.strip()
    formats = ("%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S")
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone(timedelta(hours=-3)))
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def xml_request(request_type, additional_xml, login, password):
    return f"""
<{request_type}>
    <login>{login}</login>
    <senha>{password}</senha>
    {additional_xml}
</{request_type}>
""".strip()


def unpack_response(content):
    if zipfile.is_zipfile(io.BytesIO(content)):
        payloads = []
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            for name in archive.namelist():
                if name.endswith("/"):
                    continue
                raw = archive.read(name)
                payloads.append(raw.decode("utf-8-sig", errors="replace"))
        return payloads
    return [content.decode("utf-8-sig", errors="replace")]


def init_db(conn, schema_name="trucks"):
    schema = quote_ident(schema_name)
    schema_path = Path(__file__).with_name("schema.sql")
    schema_sql = schema_path.read_text(encoding="utf-8")
    schema_sql = schema_sql.replace("CREATE SCHEMA IF NOT EXISTS trucks;", f"CREATE SCHEMA IF NOT EXISTS {schema};")
    schema_sql = schema_sql.replace("trucks.", f"{schema}.")
    with conn.cursor() as cur:
        cur.execute(schema_sql)
        for job_name, config in JOBS.items():
            cur.execute(
                """
                INSERT INTO {schema}.integration_jobs (job_name, request_type, interval_seconds)
                VALUES (%s, %s, %s)
                ON CONFLICT (job_name) DO UPDATE SET
                    request_type = EXCLUDED.request_type,
                    interval_seconds = EXCLUDED.interval_seconds,
                    updated_at = now()
                """.format(schema=schema),
                (job_name, config["request_type"], config["interval_seconds"]),
            )
    conn.commit()


def enqueue_payload(conn, schema, job_name, http_status, payload):
    source_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {schema}.{job_name}_temp (source_hash, http_status, payload, payload_size)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (source_hash) DO NOTHING
            RETURNING id
            """,
            (source_hash, http_status, payload, len(payload)),
        )
        inserted = cur.fetchone() is not None
    return source_hash, inserted


def fetch_job(conn, client, job_name):
    import requests

    config = JOBS[job_name]
    body = xml_request(config["request_type"], config["additional_xml"], client["login"], client["password"])
    response = requests.post(
        client["api_url"],
        data=body.encode("utf-8"),
        headers={"Content-Type": "application/xml"},
        timeout=60,
    )
    payloads = unpack_response(response.content)

    new_payloads = 0
    for payload in payloads:
        source_hash, inserted = enqueue_payload(conn, client["schema"], job_name, response.status_code, payload)
        if inserted:
            new_payloads += 1
        if "<ErrorRequest>" in payload:
            raise RuntimeError(f"Trucks retornou ErrorRequest no payload {source_hash}")

    conn.commit()
    return new_payloads


def process_pending(conn, schema, job_name, limit=20):
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, source_hash, requested_at, http_status, payload, payload_size
            FROM {schema}.{job_name}_temp
            WHERE status IN ('pending', 'error')
            ORDER BY created_at
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()

    totals = {"read": 0, "inserted": 0, "ignored": 0}
    for row in rows:
        temp_id, source_hash, requested_at, http_status, payload, payload_size = row
        try:
            read_count, inserted_count = process_payload(conn, schema, job_name, payload, source_hash)
            ignored_count = max(read_count - inserted_count, 0)
            move_to_importados(
                conn,
                schema,
                job_name,
                temp_id,
                source_hash,
                requested_at,
                http_status,
                payload,
                payload_size,
                read_count,
                inserted_count,
                ignored_count,
            )
            conn.commit()
            totals["read"] += read_count
            totals["inserted"] += inserted_count
            totals["ignored"] += ignored_count
        except Exception as exc:
            conn.rollback()
            mark_temp_error(conn, schema, job_name, temp_id, source_hash, str(exc))
            conn.commit()
    return totals


def process_payload(conn, schema, job_name, payload, source_hash):
    root = ET.fromstring(payload)
    if job_name == "veiculos":
        return insert_veiculos(conn, schema, root, source_hash)
    if job_name == "mensagens_cb":
        return insert_mensagens_cb(conn, schema, root, source_hash)
    if job_name == "ocorrencias_telemetria":
        return insert_ocorrencias(conn, schema, root, source_hash)
    if job_name == "telemetria_relatorio":
        return insert_telemetria_relatorio(conn, schema, root, source_hash)
    raise ValueError(f"Job desconhecido: {job_name}")


def rowcount_after_execute(cur):
    return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0


def insert_veiculos(conn, schema, root, source_hash):
    read_count = 0
    inserted_count = 0
    sql = """
        INSERT INTO {schema}.veiculos (
            veiculo_id, placa, versao_comp_bordo, sensor_temp1, sensor_temp2, sensor_temp3,
            tempo_reenvio_comando, teclado_macro, permissao_envio_comando, temporizador_padrao,
            temporizador_satelital_atual, tipo_equipamento, nome_motorista, proprietario,
            direito_inteligencia_embarcada, inteligencia_embarcada, localizador,
            identificacao_equipamento, manutencao, data_expiracao_espelhamento,
            direito_cancelar_espelhamento, permissao_compartilhar, temporizador_gsm,
            permissao_alterar_pos_satelital, temporizador_pos_parado,
            temporizador_pos_parado_menor_60, chassi, ultima_manutencao_at, source_hash
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT (veiculo_id) DO UPDATE SET
            placa = EXCLUDED.placa,
            versao_comp_bordo = EXCLUDED.versao_comp_bordo,
            nome_motorista = EXCLUDED.nome_motorista,
            identificacao_equipamento = EXCLUDED.identificacao_equipamento,
            chassi = EXCLUDED.chassi,
            ultima_manutencao_at = EXCLUDED.ultima_manutencao_at,
            source_hash = EXCLUDED.source_hash,
            updated_at = now()
        RETURNING (xmax = 0) AS inserted
    """.format(schema=schema)
    with conn.cursor() as cur:
        for veiculo in root.findall("Veiculo"):
            read_count += 1
            cur.execute(
                sql,
                (
                    to_int(text_of(veiculo, "veiID")),
                    text_of(veiculo, "placa"),
                    to_decimal(text_of(veiculo, "vs")),
                    to_bool(text_of(veiculo, "st1")),
                    to_bool(text_of(veiculo, "st2")),
                    to_bool(text_of(veiculo, "st3")),
                    to_int(text_of(veiculo, "tCmd")),
                    to_bool(text_of(veiculo, "tMac")),
                    to_bool(text_of(veiculo, "eCmd")),
                    to_int(text_of(veiculo, "tp")),
                    to_int(text_of(veiculo, "ta")),
                    to_int(text_of(veiculo, "eqp")),
                    text_of(veiculo, "mot"),
                    to_bool(text_of(veiculo, "prop")),
                    to_bool(text_of(veiculo, "dIE")),
                    to_bool(text_of(veiculo, "IE")),
                    to_bool(text_of(veiculo, "loc")),
                    text_of(veiculo, "ident"),
                    to_bool(text_of(veiculo, "vManut")),
                    to_datetime(text_of(veiculo, "valEspelhamento")),
                    to_bool(text_of(veiculo, "propCancelamento")),
                    to_bool(text_of(veiculo, "podeCompartilhar")),
                    to_int(text_of(veiculo, "tgsm")),
                    to_bool(text_of(veiculo, "ppc")),
                    to_int(text_of(veiculo, "tppc")),
                    to_int(text_of(veiculo, "ppcMenor60")),
                    text_of(veiculo, "chassi"),
                    to_datetime(text_of(veiculo, "uManut")),
                    source_hash,
                ),
            )
            inserted_count += 1 if cur.fetchone()[0] else 0
    return read_count, inserted_count


def insert_mensagens_cb(conn, schema, root, source_hash):
    read_count = 0
    inserted_count = 0
    sql = """
        INSERT INTO {schema}.mensagens_cb (
            mensagem_id, veiculo_id, data_hora, latitude, longitude, municipio, uf,
            rodovia, rua, velocidade, evt2_sirene_acionada, evt3_veiculo_bloqueado,
            evt4_ignicao_acionada, evt12_porta_carona_aberta, evt13_porta_motorista_aberta,
            origem_mensagem, tipo_mensagem, data_hora_inclusao, odometro, bateria_carreta,
            rpm, evt27_desengate_carreta2, evento_gerador, alerta_telemetria, source_hash
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT (mensagem_id) DO NOTHING
    """.format(schema=schema)
    with conn.cursor() as cur:
        for mensagem in root.findall("MensagemCB"):
            read_count += 1
            cur.execute(
                sql,
                (
                    to_int(text_of(mensagem, "mId")),
                    to_int(text_of(mensagem, "veiID")),
                    to_datetime(text_of(mensagem, "dt")),
                    to_decimal(text_of(mensagem, "lat")),
                    to_decimal(text_of(mensagem, "lon")),
                    text_of(mensagem, "mun"),
                    text_of(mensagem, "uf"),
                    text_of(mensagem, "rod"),
                    text_of(mensagem, "rua"),
                    to_int(text_of(mensagem, "vel")),
                    to_bool(text_of(mensagem, "evt2")),
                    to_bool(text_of(mensagem, "evt3")),
                    to_bool(text_of(mensagem, "evt4")),
                    to_bool(text_of(mensagem, "evt12")),
                    to_bool(text_of(mensagem, "evt13")),
                    to_int(text_of(mensagem, "ori")),
                    to_int(text_of(mensagem, "tpMsg")),
                    to_datetime(text_of(mensagem, "dtInc")),
                    to_int(text_of(mensagem, "odm")),
                    to_decimal(text_of(mensagem, "bat")),
                    to_int(text_of(mensagem, "rpm")),
                    to_bool(text_of(mensagem, "evt27")),
                    to_int(text_of(mensagem, "evtG")),
                    text_of(mensagem, "alrtTelem"),
                    source_hash,
                ),
            )
            inserted_count += rowcount_after_execute(cur)
    return read_count, inserted_count


def insert_ocorrencias(conn, schema, root, source_hash):
    read_count = 0
    inserted_count = 0
    sql = """
        INSERT INTO {schema}.ocorrencias_telemetria (
            veiculo_id, data_hora, velocidade, rpm, velocidade_max,
            porcentagem_tanque, source_hash
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (
            veiculo_id, data_hora, velocidade, rpm, velocidade_max, porcentagem_tanque
        ) DO NOTHING
    """.format(schema=schema)
    with conn.cursor() as cur:
        for ocorrencia in root.findall("Ocorrencia"):
            read_count += 1
            cur.execute(
                sql,
                (
                    to_int(text_of(ocorrencia, "veiID")),
                    to_datetime(text_of(ocorrencia, "dtHr")),
                    to_int(text_of(ocorrencia, "vel")),
                    to_int(text_of(ocorrencia, "rpm")),
                    to_int(text_of(ocorrencia, "velMax")),
                    to_decimal(text_of(ocorrencia, "pTanque")),
                    source_hash,
                ),
            )
            inserted_count += rowcount_after_execute(cur)
    return read_count, inserted_count


def insert_telemetria_relatorio(conn, schema, root, source_hash):
    read_count = 0
    inserted_count = 0
    data_referencia = date.today() - timedelta(days=int(os.getenv("TRUCKS_TELEMETRIA_DIAS_ATRAS", "1")))
    sql = """
        INSERT INTO {schema}.telemetria_relatorio (
            veiculo_id, data_referencia, distancia, velocidade_media, velocidade_max,
            hora_ini, hora_fim, utilizacao, hodometro_ini, hodometro_fim,
            media_consumo, consumo_hora_motor, rpm_medio, rpm_max, temperatura_media,
            total_motor_lig, total_motor_deslig, total_motor_lig_mov, total_motor_lig_par,
            source_hash
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s::interval, %s::interval, %s::interval, %s::interval, %s
        )
        ON CONFLICT (veiculo_id, data_referencia) DO UPDATE SET
            distancia = EXCLUDED.distancia,
            velocidade_media = EXCLUDED.velocidade_media,
            velocidade_max = EXCLUDED.velocidade_max,
            hodometro_ini = EXCLUDED.hodometro_ini,
            hodometro_fim = EXCLUDED.hodometro_fim,
            media_consumo = EXCLUDED.media_consumo,
            consumo_hora_motor = EXCLUDED.consumo_hora_motor,
            rpm_medio = EXCLUDED.rpm_medio,
            rpm_max = EXCLUDED.rpm_max,
            temperatura_media = EXCLUDED.temperatura_media,
            total_motor_lig = EXCLUDED.total_motor_lig,
            total_motor_deslig = EXCLUDED.total_motor_deslig,
            total_motor_lig_mov = EXCLUDED.total_motor_lig_mov,
            total_motor_lig_par = EXCLUDED.total_motor_lig_par,
            source_hash = EXCLUDED.source_hash,
            updated_at = now()
        RETURNING (xmax = 0) AS inserted
    """.format(schema=schema)
    with conn.cursor() as cur:
        for relatorio in root.findall("Relatorio"):
            read_count += 1
            cur.execute(
                sql,
                (
                    to_int(text_of(relatorio, "veiID")),
                    data_referencia,
                    to_int(text_of(relatorio, "distancia")),
                    to_int(text_of(relatorio, "velMedia")),
                    to_int(text_of(relatorio, "velMax")),
                    to_int(text_of(relatorio, "horIni")),
                    to_int(text_of(relatorio, "horFim")),
                    to_int(text_of(relatorio, "utilizacao")),
                    to_int(text_of(relatorio, "odmIni")),
                    to_int(text_of(relatorio, "odmFim")),
                    to_decimal(text_of(relatorio, "mediaConsumo")),
                    to_decimal(text_of(relatorio, "consHoraMotor")),
                    to_int(text_of(relatorio, "rpmMedio")),
                    to_int(text_of(relatorio, "rpmMax")),
                    to_int(text_of(relatorio, "tempMedia")),
                    text_of(relatorio, "totalMotorLig"),
                    text_of(relatorio, "totalMotorDeslig"),
                    text_of(relatorio, "totalMotorLigMov"),
                    text_of(relatorio, "totalMotorLigPar"),
                    source_hash,
                ),
            )
            inserted_count += 1 if cur.fetchone()[0] else 0
    return read_count, inserted_count


def move_to_importados(
    conn,
    schema,
    job_name,
    temp_id,
    source_hash,
    requested_at,
    http_status,
    payload,
    payload_size,
    records_read,
    records_inserted,
    records_ignored,
):
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {schema}.{job_name}_importados (
                source_hash, requested_at, http_status, payload, payload_size,
                records_read, records_inserted, records_ignored
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_hash) DO NOTHING
            """,
            (
                source_hash,
                requested_at,
                http_status,
                payload,
                payload_size,
                records_read,
                records_inserted,
                records_ignored,
            ),
        )
        cur.execute(f"DELETE FROM {schema}.{job_name}_temp WHERE id = %s", (temp_id,))


def mark_temp_error(conn, schema, job_name, temp_id, source_hash, error_message):
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE {schema}.{job_name}_temp
            SET status = 'error',
                attempts = attempts + 1,
                last_error = %s,
                updated_at = now()
            WHERE id = %s
            """,
            (error_message[:2000], temp_id),
        )
        cur.execute(
            f"""
            INSERT INTO {schema}.integration_errors (job_name, stage, error_message, source_hash)
            VALUES (%s, %s, %s, %s)
            """,
            (job_name, "parse_import", error_message[:2000], source_hash),
        )


def due_jobs(conn, schema, only_job=None):
    if only_job:
        return [only_job]
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT job_name
            FROM {schema}.integration_jobs
            WHERE enabled = true
              AND next_run_at <= now()
            ORDER BY next_run_at
            """
        )
        return [row[0] for row in cur.fetchall()]


def update_job_success(conn, schema, job_name, totals):
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE {schema}.integration_jobs
            SET last_success_at = now(),
                last_status = 'success',
                last_error_message = NULL,
                next_run_at = now() + make_interval(secs => interval_seconds),
                last_records_inserted = %s,
                last_records_ignored = %s,
                updated_at = now()
            WHERE job_name = %s
            """,
            (totals["inserted"], totals["ignored"], job_name),
        )


def update_job_error(conn, schema, job_name, error_message):
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE {schema}.integration_jobs
            SET last_error_at = now(),
                last_status = 'error',
                last_error_message = %s,
                next_run_at = now() + interval '5 minutes',
                updated_at = now()
            WHERE job_name = %s
            """,
            (error_message[:2000], job_name),
        )
        cur.execute(
            f"""
            INSERT INTO {schema}.integration_errors (job_name, stage, error_message)
            VALUES (%s, %s, %s)
            """,
            (job_name, "fetch_job", error_message[:2000]),
        )


def run_once(conn, only_job=None, only_client=None):
    clients = active_clients(conn, only_client)
    if not clients:
        print("Nenhum cliente com credenciais Trucks ativas.")
        return
    for client in clients:
        schema = client["schema"]
        jobs = due_jobs(conn, schema, only_job)
        if not jobs:
            continue
        for job_name in jobs:
            try:
                fetch_job(conn, client, job_name)
                totals = process_pending(conn, schema, job_name)
                update_job_success(conn, schema, job_name, totals)
                conn.commit()
                print(
                    f"{client['slug']}/{job_name}: lidos={totals['read']} "
                    f"inseridos={totals['inserted']} ignorados={totals['ignored']}"
                )
            except Exception as exc:
                conn.rollback()
                update_job_error(conn, schema, job_name, str(exc))
                conn.commit()
                print(f"{client['slug']}/{job_name}: erro={exc}")


def main():
    parser = argparse.ArgumentParser(description="Ingestao Trucks API para PostgreSQL")
    parser.add_argument("--init-db", action="store_true", help="Cria schema e tabelas")
    parser.add_argument("--once", action="store_true", help="Executa uma rodada")
    parser.add_argument("--loop", action="store_true", help="Executa em loop")
    parser.add_argument("--job", choices=sorted(JOBS), help="Executa apenas um job")
    parser.add_argument("--client", help="Executa apenas um cliente pelo slug ou schema")
    parser.add_argument("--schema", default="trucks", help="Schema usado com --init-db")
    parser.add_argument("--sleep", type=int, default=60, help="Pausa do loop em segundos")
    args = parser.parse_args()

    with connect(include_api=not args.init_db or args.once or args.loop) as conn:
        if args.init_db:
            init_db(conn, args.schema)
            print(f"Schema/tabelas criados ou atualizados em {args.schema}.")
        if args.loop:
            while True:
                run_once(conn, args.job, args.client)
                time.sleep(args.sleep)
        elif args.once or not args.init_db:
            run_once(conn, args.job, args.client)


if __name__ == "__main__":
    main()
