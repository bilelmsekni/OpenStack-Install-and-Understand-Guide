from django.utils.translation import ugettext_lazy as _
from django.template.defaultfilters import timesince, floatformat

from horizon import tables
from horizon.templatetags.sizeformat import mbformat


class CSVSummary(tables.LinkAction):
    name = "csv_summary"
    verbose_name = _("Download CSV Summary")
    classes = ("btn-download",)

    def get_link_url(self, usage=None):
        return self.table.kwargs['usage'].csv_link()


class BaseUsageTable(tables.DataTable):
    vcpus = tables.Column('vcpus', verbose_name=_("VCPUs"))
    disk = tables.Column('local_gb', verbose_name=_("Disk"))
    memory = tables.Column('memory_mb',
                           verbose_name=_("RAM"),
                           filters=(mbformat,))
    hours = tables.Column('vcpu_hours', verbose_name=_("VCPU Hours"),
                          filters=(lambda v: floatformat(v, 2),))


class GlobalUsageTable(BaseUsageTable):
    tenant = tables.Column('tenant_id', verbose_name=_("Project ID"))
    disk_hours = tables.Column('disk_gb_hours',
                               verbose_name=_("Disk GB Hours"),
                               filters=(lambda v: floatformat(v, 2),))

    def get_object_id(self, datum):
        return datum.tenant_id

    class Meta:
        name = "global_usage"
        verbose_name = _("Usage Summary")
        columns = ("tenant", "vcpus", "disk", "memory",
                   "hours", "disk_hours")
        table_actions = (CSVSummary,)
        multi_select = False


class TenantUsageTable(BaseUsageTable):
    instance = tables.Column('name', verbose_name=_("Instance Name"))
    uptime = tables.Column('uptime_at',
                           verbose_name=_("Uptime"),
                           filters=(timesince,))

    def get_object_id(self, datum):
        return id(datum)

    class Meta:
        name = "tenant_usage"
        verbose_name = _("Usage Summary")
        columns = ("instance", "vcpus", "disk", "memory", "uptime")
        table_actions = (CSVSummary,)
        multi_select = False
