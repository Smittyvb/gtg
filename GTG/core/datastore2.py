# -----------------------------------------------------------------------------
# Getting Things GNOME! - a personal organizer for the GNOME desktop
# Copyright (c) The GTG Team
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program.  If not, see <http://www.gnu.org/licenses/>.
# -----------------------------------------------------------------------------

"""The datastore ties together all the basic type stores and backends."""

import os
import threading
import logging
import shutil
from datetime import datetime
from time import time

from GTG.core.tasks2 import TaskStore
from GTG.core.tags2 import TagStore
from GTG.core.saved_searches import SavedSearchStore
from GTG.core import firstrun_tasks
from GTG.backends.backend_signals import BackendSignals

from lxml import etree as et


log = logging.getLogger(__name__)


class Datastore2:

    #: Amount of backups to keep
    BACKUPS_NUMBER = 7


    def __init__(self) -> None:
        self.tasks = TaskStore()
        self.tags = TagStore()
        self.saved_searches = SavedSearchStore()
        self.xml_tree = None

        self._mutex = threading.Lock()
        self.backends = {}
        self._backend_signals = None

        # Flag when turned to true, all pending operation should be
        # completed and then GTG should quit
        self.please_quit = False


    @property
    def mutex(self) -> threading.Lock:
        return self._mutex


    def load_data(self, data: et.Element) -> None:

        self.saved_searches.from_xml(data.find('searchlist'))
        self.tags.from_xml(data.find('taglist'))
        self.tasks.from_xml(data.find('tasklist'), self.tags)


    def load_file(self, path: str) -> None:

        if log.isEnabledFor(logging.DEBUG):
            bench_start = time()

        parser = et.XMLParser(remove_blank_text=True, strip_cdata=False)

        with open(path, 'rb') as stream:
            self.tree = et.parse(stream, parser=parser)
            self.load_data(self.tree)

        if log.isEnabledFor(logging.DEBUG):
            log.debug('Processed file %s in %.2fms',
                      path, (time() - bench_start) * 1000)


    def generate_xml(self) -> et.ElementTree:

        root = et.Element('gtgData')
        root.set('appVersion', '0.5')
        root.set('xmlVersion', '2')

        root.append(self.tags.to_xml())
        root.append(self.saved_searches.to_xml())
        root.append(self.tasks.to_xml())

        return et.ElementTree(root)


    def save_file(self, path: str) -> None:

        temp_file = path + '__'

        if os.path.exists(path):
            os.rename(path, temp_file)

        if log.isEnabledFor(logging.DEBUG):
            bench_start = time()

        tree = self.generate_xml()

        try:
            with open(path, 'wb') as stream:
                tree.write(stream, xml_declaration=True,
                        pretty_print=True,
                        encoding='UTF-8')

        except (IOError, FileNotFoundError):
            log.error('Could not write XML file at %r', path)

            base_dir = os.path.dirname(filepath)

            try:
                os.makedirs(base_dir, exist_ok=True)
            except IOError as error:
                log.error("Error while creating directories: %r", error)

        if log.isEnabledFor(logging.DEBUG):
            log.debug('Saved file %s in %.2fms',
                      path, (time() - bench_start) * 1000)

        if os.path.exists(temp_file):
            os.remove(temp_file)

        self.write_backups(path)


    def print_info(self) -> None:

        tasks = self.tasks.count()
        initialized = 'Initialized' if tasks > 0 else 'Empty'

        print(f'Datastore [{initialized}]')
        print(f'- Tags: {self.tags.count()}')
        print(f'- Saved Searches: {self.saved_searches.count()}')
        print(f'- Tasks: {self.tasks.count()}')


    def first_run(self, path: str) -> et.Element:
        """Write intial data file."""

        self.tree = firstrun_tasks.generate()
        self.load_data(self.tree)
        self.save_file(path)


    def get_backup_name(self, path: str, i: int = None) -> str:
        """Get name of backups which are backup/ directory."""

        dirname, filename = os.path.split(path)
        backup_file = f"{filename}.bak.{i}" if i else filename

        return os.path.join(dirname, 'backup', backup_file)


    def write_backups(self, path: str) -> None:
        current_backup = self.BACKUPS
        backup_name = self.get_backup_name(filepath)
        backup_dir = os.path.dirname(backup_name)

        # Make sure backup dir exists
        try:
            os.makedirs(backup_dir, exist_ok=True)

        except IOError:
            log.error('Backup dir %r cannot be created!', backup_dir)
            return

        # Cycle backups
        while current_backup > 0:
            older = f"{backup_name}.bak.{current_backup}"
            newer = f"{backup_name}.bak.{current_backup - 1}"

            if os.path.exists(newer):
                shutil.move(newer, older)

            current_backup -= 1

        # bak.0 is always a fresh copy of the closed file
        # so that it's not touched in case of not opening next time
        bak_0 = f"{backup_name}.bak.0"
        shutil.copy(filepath, bak_0)

        # Add daily backup
        today = datetime.today().strftime('%Y-%m-%d')
        daily_backup = f'{backup_name}.{today}.bak'

        if not os.path.exists(daily_backup):
            shutil.copy(filepath, daily_backup)


    def find_and_load_file(self, path: str) -> str:
        """Find an XML file to open

        If file could not be opened, try:
            - file__
            - file.bak.0
            - file.bak.1
            - .... until BACKUP_NBR

        If file doesn't exist, create a new file."""

        files = [
            xml_path,            # Main file
            xml_path + '__',     # Temp file
        ]

        # Add backup files
        files += [self.get_backup_name(xml_path, i)
                  for i in range(self.BACKUPS)]

        backup_info = None

        for index, filepath in enumerate(files):
            try:
                log.debug('Opening file %s', filepath)
                self.load_file(filepath)

                timestamp = os.path.getmtime(filepath)
                mtime = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d')

                # This was a backup. We should inform the user
                if index > 0:
                    backup_info = {
                        'name': filepath,
                        'time': mtime
                    }

                # We could open a file, let's stop this loop
                break

            except FileNotFoundError:
                log.debug('File not found: %r. Trying next.', filepath)
                continue

            except PermissionError:
                log.debug('Not allowed to open: %r. Trying next.', filepath)
                continue

            except etree.XMLSyntaxError as error:
                log.debug('Syntax error in %r. %r. Trying next.',
                          filepath, error)
                continue

        # We couldn't open any file :(
        if not self.tree:
            try:
                # Try making a new empty file and open it
                self.first_run(path)
                return self.load_file(path)

            except IOError:
                raise SystemError(f'Could not write a file at {path}')


    # --------------------------------------------------------------------------
    # BACKENDS
    # --------------------------------------------------------------------------

    def get_all_backends(self, disabled=False):
        """
        returns list of all registered backends for this DataStore.

        @param disabled: If disabled is True, attaches also the list of
                disabled backends
        @return list: a list of TaskSource objects
        """
        result = []
        for backend in self.backends.values():
            if backend.is_enabled() or disabled:
                result.append(backend)
        return result


    def activate_backends(self, sender=None):
        """
        Non-default backends have to wait until the default loads before
        being  activated. This function is called after the first default
        backend has loaded all its tasks.

        @param sender: not used, just here for signal compatibility
        """

        self._backend_signals = BackendSignals()
        for backend in self.backends.values():
            if backend.is_enabled() and not backend.is_default():
                self._backend_startup(backend)


    def _backend_startup(self, backend):
        """
        Helper function to launch a thread that starts a backend.

        @param backend: the backend object
        """

        def __backend_startup(self, backend):
            """
            Helper function to start a backend

            @param backend: the backend object
            """
            backend.initialize()
            backend.start_get_tasks()
            self.flush_all_tasks(backend.get_id())

        thread = threading.Thread(target=__backend_startup,
                                  args=(self, backend))
        thread.setDaemon(True)
        thread.start()


    def set_backend_enabled(self, backend_id, state):
        """
        The backend corresponding to backend_id is enabled or disabled
        according to "state".
        Disable:
        Quits a backend and disables it (which means it won't be
        automatically loaded next time GTG is started)
        Enable:
        Reloads a disabled backend. Backend must be already known by the
        Datastore

        @param backend_id: a backend id
        @param state: True to enable, False to disable
        """
        if backend_id in self.backends:
            backend = self.backends[backend_id]
            current_state = backend.is_enabled()
            if current_state is True and state is False:
                # we disable the backend
                # FIXME!!!
                threading.Thread(target=backend.quit,
                                 kwargs={'disable': True}).start()
            elif current_state is False and state is True:
                    self._backend_startup(backend)


    def backend_change_attached_tags(self, backend_id, tag_names):
        """
        Changes the tags for which a backend should store a task

        @param backend_id: a backend_id
        @param tag_names: the new set of tags. This should not be a tag object,
                          just the tag name.
        """
        backend = self.backends[backend_id]
        backend.set_attached_tags(tag_names)


    def flush_all_tasks(self, backend_id):
        """
        This function will cause all tasks to be checked against the backend
        identified with backend_id. If tasks need to be added or removed, it
        will be done here.
        It has to be run after the creation of a new backend (or an alteration
        of its "attached tags"), so that the tasks which are already loaded in
        the Tree will be saved in the proper backends

        @param backend_id: a backend id
        """

        def _internal_flush_all_tasks():
            backend = self.backends[backend_id]
            for task_id in self.tasks.lookup.values():
                if self.please_quit:
                    break
                backend.queue_set_task(task_id)

        t = threading.Thread(target=_internal_flush_all_tasks)
        t.start()
        self.backends[backend_id].start_get_tasks()
