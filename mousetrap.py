from dataclasses import dataclass
from typing import Any, List, Tuple
import time
from sys import stderr
from logging import getLogger, INFO, Formatter, StreamHandler, basicConfig
from pyautogui import size as screen_size, position as mouse_position, Point, Size
from mysql import connector
import click
from datetime import datetime
from collections import namedtuple
import numpy
from matplotlib import pyplot


Scale = namedtuple("Scale", "width height")
VizData = namedtuple("VizData", "timestamp point")


slog = getLogger(__name__)
format = Formatter("%(asctime)s %(levelname)s %(funcName)s:%(lineno)d :: %(message)s")
handler = StreamHandler(stderr)
handler.setFormatter(format)
handler.setLevel(INFO)
slog.addHandler(handler)


def db_record_mouse_position(
    *,
    db_handle: connector.MySQLConnection,
    table: str,
    time: int,
    x_position: int,
    y_position: int,
    x_size: int,
    y_size: int,
):
    sql = (
        f"INSERT INTO {table} "
        f"(time, x_position, y_position, x_size, y_size) "
        f"VALUES ({time}, {x_position}, {y_position}, {x_size}, {y_size})"
    )
    slog.warning(sql)
    db_cursor = db_handle.cursor()
    db_cursor.execute(sql)
    db_cursor.close()
    db_handle.commit()


def db_select_all_mouse_position(
    *, db_handle: connector.MySQLConnection, table: str
) -> List[Tuple[Point, Size, int]]:
    sql = f"SELECT time, x_position, y_position, x_size, y_size FROM {table}"
    slog.warning(sql)
    db_cursor = db_handle.cursor()
    db_cursor.execute(sql)
    return db_cursor.fetchall()


def db_open(
    *, host: str, port: str | int, user: str, password: str, database: str | None = None
) -> connector.MySQLConnection:
    db_handle = connector.connect(
        host=host,
        port=str(port),
        user=user,
        password=password,
        database=database,
    )
    slog.warning(f"successful open DB `{database}` {db_handle}")
    return db_handle


def db_create_database(*, database: str, db_handle: connector.MySQLConnection) -> str:
    db_cursor = db_handle.cursor()
    db_cursor.execute("SHOW DATABASES")
    dbs = db_cursor.fetchall()
    slog.warning(f"found DBs {dbs}")
    if (database,) not in dbs:
        slog.warning(f"database `{database}` does not exist, creating...")
        db_cursor.execute(f"CREATE DATABASE {database}")
        slog.warning(f"database `{database}` created")
    else:
        slog.warning(f"database `{database}` already exists")
    db_cursor.close()
    return database


def db_create_table(
    *, table: str, db_handle: connector.MySQLConnection
) -> connector.MySQLConnection:
    db_cursor = db_handle.cursor()
    db_cursor.execute("SHOW TABLES")
    tables = db_cursor.fetchall()
    slog.warning(f"found tables {tables}")
    if (table,) not in tables:
        db_cursor.execute(
            f"CREATE TABLE {table} "
            f"("
            f"id INT AUTO_INCREMENT PRIMARY KEY,"
            f"time INT,"
            f"x_position INT,"
            f"y_position INT,"
            f"x_size INT,"
            f"y_size INT"
            f")"
        )
        slog.warning(f"created table `{table}`")
    else:
        slog.warning(f"table `{table}` already exists")
    return db_handle

def viz_vizdata(*, data) -> None:
    pyplot.imshow(data, cmap='viridis')
    pyplot.title("Mouse cursor heatmap")
    pyplot.show()


@click.command()
@click.option("--mysql-db-host", default="localhost")
@click.option("--mysql-db-port", default="3306")
@click.option("--mysql-db-user", default="admin")
@click.option("--mysql-db-password", default="gigachad")
@click.option("--mysql-db-name", default="mousetrap")
@click.option("--mysql-db-table", default="events")
@click.option("--sample-period", default=float(1))
@click.option("--inactivity-period", default=float(3))
def collect(
    mysql_db_host,
    mysql_db_port,
    mysql_db_user,
    mysql_db_password,
    mysql_db_name,
    mysql_db_table,
    sample_period,
    inactivity_period,
):
    RESET = 0
    db_handle = db_create_table(
        table=mysql_db_table,
        db_handle=db_open(
            host=mysql_db_host,
            port=mysql_db_port,
            user=mysql_db_user,
            password=mysql_db_password,
            database=db_create_database(
                database=mysql_db_name,
                db_handle=db_open(
                    host=mysql_db_host,
                    port=mysql_db_port,
                    user=mysql_db_user,
                    password=mysql_db_password,
                ),
            ),
        ),
    )
    (mp_prev, ss_prev) = (None, None)
    eval_inactive: float = 0
    while True:
        time.sleep(sample_period)
        (mp, ss, ts) = (mouse_position(), screen_size(), time.time())
        state_inactive = eval_inactive >= inactivity_period
        eval_inactive = (
            eval_inactive + sample_period if (mp, ss) == (mp_prev, ss_prev) else RESET
        )
        if eval_inactive >= inactivity_period:
            if not state_inactive:
                slog.warning(
                    f"suspending data collection, mouse inactive for >= {inactivity_period}"
                )
            continue
        elif state_inactive and eval_inactive < inactivity_period:
            slog.warning(f"resuming data collection, mouse wake up")
        db_record_mouse_position(
            db_handle=db_handle,
            table=mysql_db_table,
            time=int(ts),
            x_position=mp.x,
            y_position=mp.y,
            x_size=ss.width,
            y_size=ss.height,
        )
        (mp_prev, ss_prev) = (mp, ss)


@click.command()
@click.option("--mysql-db-host", default="localhost")
@click.option("--mysql-db-port", default="3306")
@click.option("--mysql-db-user", default="admin")
@click.option("--mysql-db-password", default="gigachad")
@click.option("--mysql-db-name", default="mousetrap")
@click.option("--mysql-db-table", default="events")
@click.option("--scale-width", default=int(160))
@click.option("--scale-height", default=int(90))
def visualize(
    mysql_db_host,
    mysql_db_port,
    mysql_db_user,
    mysql_db_password,
    mysql_db_name,
    mysql_db_table,
    scale_width,
    scale_height,
):
    db_handle = db_open(
        host=mysql_db_host,
        port=mysql_db_port,
        user=mysql_db_user,
        password=mysql_db_password,
        database=mysql_db_name,
    )
    all_data = db_select_all_mouse_position(
        db_handle=db_handle,
        table=mysql_db_table,
    )
    slog.warning(f"fetched {len(all_data)} entries")
    time_start = time.time()
    # ts <- timestamp
    # mp_x <- mouse position x
    # mp_y <- mouse position y
    # scale_x <- ss_x div output visualization width
    # scale_y <-ss_y div output visualization height
    # ss_x <- screen size width
    # ss_y <- screen size height
    # lambda x: x[0] <- ts
    processed_data = sorted(
        [
            VizData(ts, Point(mp_x / scale_x, mp_y / scale_y))
            for ((ts, mp_x, mp_y, _, _), (scale_x, scale_y)) in zip(
                all_data,
                [
                    (float(ss_x) / scale_width, float(ss_y) / scale_height)
                    for (_, _, _, ss_x, ss_y) in all_data
                ],
            )
        ],
        key=lambda x: x[0],
    )
    
    slog.warning(
        f"processed {len(processed_data)} "
        f"entries in {time.time() - time_start} seconds"
    )
    time_start = time.time()
    freq_matrix = numpy.zeros((scale_height, scale_width), dtype=float)
    for (_, point) in processed_data:
        freq_matrix[int(point.y), int(point.x)] += 1
    freq_matrix /= freq_matrix.max()
    slog.warning(
        f"populated frequency matrix shape {freq_matrix.shape} "
        f"entries in {time.time() - time_start} seconds"
    )
    slog.warning(
        f"plotting values between "
        f"{datetime.utcfromtimestamp(processed_data[0].timestamp).strftime('%Y-%m-%d %H:%M:%S')} - "
        f"{datetime.utcfromtimestamp(processed_data[-1].timestamp).strftime('%Y-%m-%d %H:%M:%S')}"
    )
    viz_vizdata(data=freq_matrix)


@click.group()
def main():
    pass


main.add_command(collect)
main.add_command(visualize)

if __name__ == "__main__":
    main()
