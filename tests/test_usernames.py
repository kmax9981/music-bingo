"""Checks for the rename rules (app/usernames.py). No server or database needed:  python3 tests/test_usernames.py"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('usernames', os.path.join(HERE, '..', 'app', 'usernames.py'))
un = importlib.util.module_from_spec(spec)
spec.loader.exec_module(un)
os.environ.pop('HOST_ADMIN_USER', None)
EXIST = {'admin', 'kevin', 'matthew'}
bad = 0


def check(name, cond):
    global bad
    print(('ok   ' if cond else 'FAIL ') + name)
    bad += 0 if cond else 1


check('plain rename allowed', un.check_new_username('mattlnew', 'Matthew', EXIST) == ('mattlnew', ''))
check('spaces around are trimmed', un.check_new_username('  mattlnew ', 'Matthew', EXIST)[0] == 'mattlnew')
check('empty refused', un.check_new_username('   ', 'Matthew', EXIST)[0] == '')
check('too long refused', un.check_new_username('x' * 65, 'Matthew', EXIST)[0] == '' and un.check_new_username('x' * 64, 'Matthew', EXIST)[0] != '')
check('control characters refused', un.check_new_username('a\nb', 'Matthew', EXIST)[0] == '')
check('taken name refused, any letter case', un.check_new_username('KEVIN', 'Matthew', EXIST)[0] == '')
check('only the case of your own name may change', un.check_new_username('MATTHEW', 'Matthew', EXIST)[0] == 'MATTHEW')
check('same name refused', un.check_new_username('Matthew', 'Matthew', EXIST)[0] == '')
check('nobody can become admin, any letter case', un.check_new_username('Admin', 'Matthew', EXIST)[0] == '' and un.check_new_username('ADMIN', 'Kevin', EXIST)[0] == '')
check('the local admin cannot be renamed', un.check_new_username('boss', 'admin', EXIST)[0] == '' and un.check_new_username('boss', 'Admin', EXIST)[0] == '')
os.environ['HOST_ADMIN_USER'] = 'root'
check('the reserved name follows HOST_ADMIN_USER', un.is_reserved('Root') and not un.is_reserved('admin'))
print('\n%s' % ('all checks passed' if not bad else '%d check(s) failed' % bad))
sys.exit(1 if bad else 0)
