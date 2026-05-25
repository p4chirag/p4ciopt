from src.database import Database


def test_database_query():
    # This test is the "degrading runtime" demo pattern when seeded.
    db = Database()
    db.insert({"name": "alice", "age": 30})
    db.insert({"name": "bob", "age": 25})
    rows = db.query(name="alice")
    assert len(rows) == 1
    assert rows[0]["age"] == 30


def test_db_insert():
    db = Database()
    rid = db.insert({"x": 1})
    assert rid == 1


def test_db_delete():
    db = Database()
    rid = db.insert({"x": 1})
    assert db.delete(rid) is True
    assert db.delete(rid) is False


def test_db_update():
    db = Database()
    rid = db.insert({"x": 1})
    assert db.update(rid, x=2) is True
    assert db.query(x=2)


def test_db_transaction():
    db = Database()
    ids = [db.insert({"i": i}) for i in range(5)]
    assert len(ids) == 5
    assert len(db.query()) == 5
