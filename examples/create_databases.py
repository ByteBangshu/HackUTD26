"""Create ONLY synthetic demo databases, refusing to overwrite existing files."""
import sqlite3
from pathlib import Path

PAIR_A_OLD='''
CREATE TABLE patrons (patron_no INTEGER PRIMARY KEY, display_name TEXT NOT NULL);
CREATE TABLE menu (sku INTEGER PRIMARY KEY, label TEXT NOT NULL, price_cents INTEGER NOT NULL);
CREATE TABLE checks (check_no INTEGER PRIMARY KEY, patron_no INTEGER NOT NULL REFERENCES patrons(patron_no), state TEXT NOT NULL);
CREATE TABLE entries (entry_no INTEGER PRIMARY KEY, check_no INTEGER NOT NULL REFERENCES checks(check_no), sku INTEGER NOT NULL REFERENCES menu(sku), qty INTEGER NOT NULL);
INSERT INTO patrons VALUES(1,'Synthetic Guest A');
INSERT INTO menu VALUES(10,'Synthetic Pizza',1200);
INSERT INTO checks VALUES(100,1,'P');
INSERT INTO entries VALUES(1000,100,10,2);
'''
PAIR_A_NEW='''
CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT NOT NULL, unit_cents INTEGER NOT NULL);
CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id), status TEXT NOT NULL);
CREATE TABLE order_items (id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id), product_id INTEGER NOT NULL REFERENCES products(id), quantity INTEGER NOT NULL);
'''
PAIR_B_OLD='''
CREATE TABLE guests_archive (ref INTEGER PRIMARY KEY, alias TEXT NOT NULL);
CREATE TABLE dishes_archive (code INTEGER PRIMARY KEY, caption TEXT NOT NULL, mass_grams INTEGER NOT NULL);
CREATE TABLE sales_archive (number INTEGER PRIMARY KEY, guest_ref INTEGER NOT NULL REFERENCES guests_archive(ref), gross_cents INTEGER NOT NULL);
CREATE TABLE sold_archive (line INTEGER PRIMARY KEY, sale_number INTEGER NOT NULL REFERENCES sales_archive(number), dish_code INTEGER NOT NULL REFERENCES dishes_archive(code), portions INTEGER NOT NULL);
INSERT INTO guests_archive VALUES(2,'Synthetic Guest B');
INSERT INTO dishes_archive VALUES(20,'Synthetic Soup',500);
INSERT INTO sales_archive VALUES(200,2,2450);
INSERT INTO sold_archive VALUES(2000,200,20,1);
'''
PAIR_B_NEW='''
CREATE TABLE accounts (key INTEGER PRIMARY KEY, title TEXT NOT NULL);
CREATE TABLE catalog (key INTEGER PRIMARY KEY, description TEXT NOT NULL, mass_kg REAL NOT NULL);
CREATE TABLE tickets (key INTEGER PRIMARY KEY, account_key INTEGER NOT NULL REFERENCES accounts(key), gross_dollars REAL NOT NULL);
CREATE TABLE ticket_rows (key INTEGER PRIMARY KEY, ticket_key INTEGER NOT NULL REFERENCES tickets(key), catalog_key INTEGER NOT NULL REFERENCES catalog(key), units INTEGER NOT NULL);
'''
CONTEXT_A='''Synthetic fixture data dictionary: patrons are customers; display_name is the customer name. menu rows are products; label is product name and price_cents is unit_cents, both USD cents. checks are orders; check_no is order ID and patron_no is customer ID. Source state P means paid, O means open, V means void; destination status uses paid/open/void respectively. entries are order_items; sku is product ID and qty is quantity. Preserve all IDs and records. No other source state codes are permitted by the business specification; unrecognized values must stop the future transfer.'''
CONTEXT_B='''Synthetic fixture data dictionary: guests_archive maps to accounts, ref to key and alias to title. dishes_archive maps to catalog, code to key, caption to description, mass_grams to mass_kg using a factor of 0.001. sales_archive maps to tickets, number to key, guest_ref to account_key, gross_cents to gross_dollars using a factor of 0.01 (USD). sold_archive maps to ticket_rows, line to key, sale_number to ticket_key, dish_code to catalog_key and portions to units. Preserve all IDs and records. No other unit or currency changes apply.'''

def create(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    definitions={'pair_a_old.sqlite':PAIR_A_OLD,'pair_a_new.sqlite':PAIR_A_NEW,'pair_b_old.sqlite':PAIR_B_OLD,'pair_b_new.sqlite':PAIR_B_NEW}
    if any((root/n).exists() for n in definitions):raise FileExistsError('Demo databases already exist. Use a new output directory.')
    for name,ddl in definitions.items():
        with sqlite3.connect(root/name) as db:db.executescript(ddl)
    (root/'pair_a_context.txt').write_text(CONTEXT_A)
    (root/'pair_b_context.txt').write_text(CONTEXT_B)
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--output',default='examples/databases');a=p.parse_args();create(a.output)
    print('Created four synthetic databases and two non-personal data dictionaries.')
