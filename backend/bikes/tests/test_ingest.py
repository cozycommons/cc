import zipfile

import duckdb
import pytest

from bikes.ingest import Archive, Store, parse_listing, select_archives

LEGACY = (
    'tripduration,starttime,stoptime,start station id,start station name,start station latitude,'
    'start station longitude,end station id,end station name,end station latitude,end station longitude,'
    'bikeid,usertype,birth year,gender\n'
    '1257,12/1/2014 00:00:28,12/1/2014 00:21:25,475,E 16 St & Irving Pl,40.73,-73.98,521,8 Ave & W 31 St,'
    '40.75,-73.99,16047,Customer,,0\n'
    '275,12/1/2014 00:00:43,12/1/2014 00:05:18,498,Broadway & W 32 St,40.74,-73.98,546,E 30 St & Park Ave S,'
    '40.74,-73.98,18472,Subscriber,1988.0,2\n'
)
# The header spelling of late 2016 to early 2017.
LEGACY_TITLED = (
    'Trip Duration,Start Time,Stop Time,Start Station ID,Start Station Name,Start Station Latitude,'
    'Start Station Longitude,End Station ID,End Station Name,End Station Latitude,End Station Longitude,'
    'Bike ID,User Type,Birth Year,Gender\n'
    '600,2014-11-01 00:00:01,2014-11-01 00:10:01,72,W 52 St,40.76,-73.99,79,Franklin St,40.71,-74.0,'
    '1,Subscriber,1970,1\n'
)
MODERN = (
    'ride_id,rideable_type,started_at,ended_at,start_station_name,start_station_id,end_station_name,'
    'end_station_id,start_lat,start_lng,end_lat,end_lng,member_casual\n'
    'C6426029C22F971F,electric_bike,2026-02-04 12:02:28.817,2026-02-04 12:10:27.340,Norman Ave,5666.11,'
    'Jackson Ave,6170.09,40.72,-73.95,40.74,-73.95,member\n'
    '8CA3B6A78AF59CA5,classic_bike,2026-02-01 17:20:08.324,2026-02-01 17:24:21.584,Bond St,4404.10,'
    'Amity St,4488.10,40.68,-73.98,,,casual\n'
)


def make_zip(path, members):
    with zipfile.ZipFile(path, 'w') as archive:
        for name, text in members.items():
            archive.writestr(name, text)
    return path


def ingest(tmp_path, key, members, etag='e1'):
    zip_path = make_zip(tmp_path / key, members)
    store = Store(tmp_path / 'data')
    rows = store.ingest(Archive(key, zip_path.stat().st_size, etag), zip_path)
    store.write_catalog()
    return store, rows


def query(store, sql):
    with duckdb.connect(str(store.root / 'bikes.duckdb'), read_only=True) as con:
        return con.execute(sql).fetchall()


def test_every_era_lands_in_one_schema(tmp_path):
    inner = tmp_path / 'inner.zip'
    make_zip(inner, {'201411-citibike-tripdata.csv': LEGACY_TITLED})
    store, _ = ingest(tmp_path, '2014-citibike-tripdata.zip', {
        '2014-citibike-tripdata/12_December/201412-citibike-tripdata_1.csv': LEGACY,
        '2014-citibike-tripdata/.DS_Store': '',
        '__MACOSX/2014-citibike-tripdata/._201412-citibike-tripdata_1.csv': 'junk',
        '2014-citibike-tripdata/201411.zip': inner.read_bytes(),
    })
    ingest(tmp_path, '202602-citibike-tripdata.zip', {'202602-citibike-tripdata_1.csv': MODERN})
    # A month archive's key sets the partition, whatever its member is called.
    store, _ = ingest(tmp_path, 'JC-202602-citibike-tripdata.csv.zip', {'JC-20262-citibike-tripdata.csv': MODERN})

    assert query(store, 'SELECT system, year, month, count(*) FROM trips GROUP BY ALL ORDER BY ALL') == [
        ('jc', 2026, 2, 2), ('nyc', 2014, 11, 1), ('nyc', 2014, 12, 2), ('nyc', 2026, 2, 2)]
    assert query(store, "SELECT member_casual, birth_year, gender, bike_id, started_at::VARCHAR, start_station_id "
                        "FROM trips WHERE year = 2014 AND month = 12 ORDER BY started_at") == [
        ('casual', None, 0, '16047', '2014-12-01 00:00:28', '475'),
        ('member', 1988, 2, '18472', '2014-12-01 00:00:43', '498')]
    assert query(store, "SELECT ride_id, end_lat, started_at::VARCHAR FROM trips "
                        "WHERE system = 'nyc' AND year = 2026 ORDER BY started_at") == [
        ('8CA3B6A78AF59CA5', None, '2026-02-01 17:20:08.324'),
        ('C6426029C22F971F', 40.74, '2026-02-04 12:02:28.817')]


def test_unknown_column_and_bad_timestamp_stop_the_run(tmp_path):
    with pytest.raises(ValueError, match="unknown column 'surge_price'"):
        ingest(tmp_path, '202603-citibike-tripdata.zip', {
            '202603-citibike-tripdata.csv': MODERN.replace('member_casual\n', 'member_casual,surge_price\n')
            .replace('member\n', 'member,1.5\n').replace('casual\n', 'casual,0\n')})
    with pytest.raises(ValueError, match="1 rows with unparseable times, e.g. '2026/02/04'"):
        ingest(tmp_path, '202604-citibike-tripdata.zip', {
            '202604-citibike-tripdata.csv': MODERN.replace('2026-02-04 12:02:28.817', '2026/02/04')})


def test_republished_archive_replaces_its_files(tmp_path):
    store, _ = ingest(tmp_path, '202602-citibike-tripdata.zip', {
        '202602-citibike-tripdata_1.csv': MODERN, '202602-citibike-tripdata_2.csv': MODERN})
    assert store.current(Archive('202602-citibike-tripdata.zip', 0, 'e1'))
    assert not store.current(Archive('202602-citibike-tripdata.zip', 0, 'e2'))

    store, rows = ingest(tmp_path, '202602-citibike-tripdata.zip', {'202602-citibike-tripdata_1.csv': MODERN},
                         etag='e2')
    assert rows == 2
    assert store.manifest['202602-citibike-tripdata.zip']['files'] == [
        'trips/system=nyc/year=2026/month=02/202602-citibike-tripdata_1.parquet']
    assert query(store, 'SELECT count(*) FROM trips') == [(2,)]


def test_listing_selects_archives_by_period():
    xml = b'''<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><IsTruncated>false</IsTruncated>
<Contents><Key>2023-citibike-tripdata.zip</Key><ETag>"a-9"</ETag><Size>10</Size></Contents>
<Contents><Key>202401-citibike-tripdata.zip</Key><ETag>"b"</ETag><Size>20</Size></Contents>
<Contents><Key>JC-202207-citbike-tripdata.csv.zip</Key><ETag>"c"</ETag><Size>30</Size></Contents>
<Contents><Key>index.html</Key><ETag>"d"</ETag><Size>1</Size></Contents>
</ListBucketResult>'''
    archives, truncated = parse_listing(xml)
    assert not truncated
    assert [(a.key, a.system, a.period, a.etag) for a in archives] == [
        ('2023-citibike-tripdata.zip', 'nyc', ('202301', '202312'), 'a-9'),
        ('202401-citibike-tripdata.zip', 'nyc', ('202401', '202401'), 'b'),
        ('JC-202207-citbike-tripdata.csv.zip', 'jc', ('202207', '202207'), 'c')]
    assert [a.key for a in select_archives(archives, {'nyc'}, '202306', '202401')] == [
        '2023-citibike-tripdata.zip', '202401-citibike-tripdata.zip']
