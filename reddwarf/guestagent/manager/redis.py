import os
from eventlet.green import subprocess

from reddwarf.common import utils
from reddwarf.common.exception import ProcessExecutionError
from reddwarf.common import cfg
from reddwarf.guestagent import dbaas
from reddwarf.guestagent import volume
from reddwarf.guestagent.db import models
from reddwarf.openstack.common import log as logging
from reddwarf.openstack.common import periodic_task
from reddwarf.openstack.common.gettextutils import _
from reddwarf.instance import models as rd_models

LOG = logging.getLogger(__name__)

DBAAS_REDISCNF = "/etc/dbaas/redis.cnf/redis.conf.%dM"

class Manager(periodic_task.PeriodicTasks):

    @periodic_task.periodic_task(ticks_between_runs=1)
    def update_status(self, context):
        """Update the status of the service"""
        Status.get().update()

    def change_passwords(self, context, users):
        raise NotImplementedError()

    def create_database(self, context, databases):
        raise NotImplementedError()

    def _create_dbs(self, databases, owner=None):
        raise NotImplementedError()

    def create_user(self, context, users):
        raise NotImplementedError()

    def delete_database(self, context, database):
        raise NotImplementedError()

    def delete_user(self, context, user):
        raise NotImplementedError()

    def get_user(self, context, username, hostname):
        raise NotImplementedError()

    def grant_access(self, context, username, hostname, databases):
        raise NotImplementedError()

    def revoke_access(self, context, username, hostname, database):
        raise NotImplementedError()

    def list_access(self, context, username, hostname):
        raise NotImplementedError()

    def list_databases(self, context, limit=None, marker=None,
                       include_marker=False):
           raise NotImplementedError()

    def list_users(self, context, limit=None, marker=None,
                   include_marker=False):
        raise NotImplementedError()

    def enable_root(self, context):
        raise NotImplementedError()

    def is_root_enabled(self, context):
        raise NotImplementedError()

    def prepare(self, context, databases, memory_mb, users, device_path=None,
                mount_point=None, password=None):
        """Makes ready DBAAS on a Guest container."""
        Status.get().begin_install()
        
        # Create the optdir
        utils.execute_with_timeout("sudo", "mkdir", "-p", "/opt/redis")
        #Mount
        if device_path:
            device = volume.VolumeDevice(device_path)
            device.format()
            #if a /var/lib/mysql folder exists, back it up.
            if os.path.exists("/var/redis"):
                #stop and do not update database
                app.stop_db()
                restart_mysql = True
                #rsync exiting data
                device.migrate_data("/var/redis")
            #mount the volume
            device.mount(mount_point)
            LOG.debug(_("Mounted the volume."))

        utils.execute_with_timeout("sudo", "apt-get", "install", "redis-server", "-y")
        # Give ownership of optdir to redis user
        utils.execute_with_timeout("sudo", "chown", "redis:redis", "/opt/redis")

        self._update_conf(memory_mb, password=password)

        utils.execute_with_timeout("sudo", "service", "redis-server", "restart")
        Status.get().end_install()

    def restart(self, context):
        utils.execute_with_timeout("sudo", "service", "redis-server", "restart")

    def start_db_with_conf_changes(self, context, updated_memory_size):
        # Update the conf
        self._update_conf(updated_memory_size)
        # Restart redis
        utils.execute_with_timeout("sudo", "service", "redis-server", "restart")

    def stop_db(self, context, do_not_start_on_reboot=False):
        utils.execute_with_timeout("sudo", "service", "redis-server", "stop")

    def get_filesystem_stats(self, context, fs_path="/opt/redis"):
        """ Gets the filesystem stats for the path given """
        return dbaas.Interrogator().get_filesystem_volume_stats(fs_path)

    def _update_conf(self, memory_size, password=None):
        utils.execute_with_timeout("sudo", "apt-get", "--force-yes", "-y", "install", "dbaas-rediscnf")
        utils.execute_with_timeout("sudo", "rm", "/etc/redis/redis.conf")
        redis_conf = DBAAS_REDISCNF % memory_size
        utils.execute_with_timeout("sudo", "ln", "-s", redis_conf, "/etc/redis/redis.conf")

        # Add the password to the redis server, but be sure to save it for resizes
        if password:
            with open("/tmp/password.conf", "a") as conf:
                conf.write("requirepass %s" % password)
            # Move w/ linux commands
            utils.execute_with_timeout("sudo", "mv", "/tmp/password.conf", "/opt/redis")

        process = subprocess.Popen("cat /opt/redis/password.conf | sudo tee -a /etc/redis/redis.conf", shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
        process.wait()


CONF = cfg.CONF


class Status(object):
    _instance = None
    
    def __init__(self):
        if self._instance is not None:
            raise RuntimeError("Cannot instantiate twice.")
        self.status = self._load_status()

    @classmethod
    def get(cls):
        if not cls._instance:
            cls._instance = Status()
        return cls._instance

    @property
    def is_redis_installed(self):
        return (self.status is not None and
                self.status != rd_models.ServiceStatuses.BUILDING and
                self.status != rd_models.ServiceStatuses.FAILED)

    @staticmethod
    def _load_status():
        """Loads the status from the database."""
        id = CONF.guest_id
        return rd_models.InstanceServiceStatus.find_by(instance_id=id)

    def begin_install(self):
        self.set_status(rd_models.ServiceStatuses.BUILDING)

    def end_install(self):
        LOG.info("Ending install_if_needed or restart.")
        self.restart_mode = False
        real_status = self._get_actual_db_status()
        LOG.info("Updating status to %s" % real_status)
        self.set_status(real_status)

    def _get_actual_db_status(self):
        try:
            out, err = utils.execute_with_timeout(
                "ps", "aux")
            for line in out.split("\n"):
                if "redis-server" in line:
                    LOG.info("Service Status is RUNNING.")
                    return rd_models.ServiceStatuses.RUNNING
            else:
                return rd_models.ServiceStatuses.SHUTDOWN
        except ProcessExecutionError as e:
            return rd_models.ServiceStatuses.SHUTDOWN

    def set_status(self, status):
        db_status = self._load_status()
        db_status.set_status(status)
        db_status.save()
        self.status = status

    def update(self):
        if self.is_redis_installed:
            LOG.info("Determining status of Redis app...")
            status = self._get_actual_db_status()
            self.set_status(status)
        else:
            LOG.info("Redis is not installed yet")