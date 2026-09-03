"""Deterministic fake standalone ESXi inventory objects."""

from types import SimpleNamespace


def ns(**values):
    """Return a compact attribute-based fake SDK object."""

    return SimpleNamespace(**values)


class FakeEsxiService:
    """Fake pyVmomi service instance exposing read-only content."""

    def __init__(self, host):
        self.host = host

    def RetrieveContent(self):
        return ns(rootFolder=ns(childEntity=[self.host]))


def fake_esxi_service(
        vm_name='APP-VM',
        power_state='poweredOn',
        tools_available=True,
        optional_hardware=True,
):
    """Return one ESXi host with one VM, datastore, disk, and NIC."""

    datastore = ns(
        name='datastore1',
        summary=ns(
            name='datastore1',
            type='VMFS',
            capacity=500 * 1024**3,
            freeSpace=200 * 1024**3,
            accessible=True,
        ),
    )
    virtual_disk = ns(
        key=2000,
        capacityInKB=20 * 1024**2,
        deviceInfo=ns(label='Hard disk 1'),
        backing=ns(datastore=datastore),
    )
    virtual_nic = ns(
        key=4000,
        macAddress='00:50:56:AA:BB:CC',
        deviceInfo=ns(label='Network adapter 1'),
        backing=ns(deviceName='VM Network'),
    )
    guest = ns()
    if tools_available:
        guest.net = [ns(
            deviceConfigId=4000,
            macAddress='00:50:56:AA:BB:CC',
            ipConfig=ns(ipAddress=[
                ns(ipAddress='192.0.2.50', prefixLength=24),
            ]),
            ipAddress=['192.0.2.50'],
        )]
    vm = ns(
        _moId='vm-42',
        name=vm_name,
        config=ns(
            instanceUuid='503c5ad7-0000-1111-2222-0123456789ab',
            uuid='42000000-1111-2222-3333-0123456789ab',
            hardware=ns(
                numCPU=4,
                memoryMB=8192,
                device=[virtual_disk, virtual_nic],
            ),
        ),
        runtime=ns(powerState=power_state),
        guest=guest,
    )
    cpu_info = (
        ns(numCpuPackages=2, numCpuCores=16, numCpuThreads=32)
        if optional_hardware
        else ns()
    )
    cpu_packages = (
        [ns(description='Intel Xeon Gold', vendor='GenuineIntel')]
        if optional_hardware
        else []
    )
    host_disk = ns(
        deviceName='/vmfs/devices/disks/naa.test',
        model='FAKE SSD',
        serialNumber='FAKE-SERIAL',
        capacity=ns(block=1000, blockSize=512),
        deviceType='disk',
        operationalState=['ok'],
    )
    host = ns(
        _moId='host-10',
        name='esxi-a.example.test',
        hardware=ns(
            systemInfo=ns(uuid='420f37d2-7a3b-4c1d-8e9f-001122334455'),
            cpuInfo=cpu_info,
            cpuPkg=cpu_packages,
            memorySize=128 * 1024**3,
        ),
        summary=ns(
            config=ns(product=ns(version='8.0.3', build='24022510')),
        ),
        config=ns(
            network=ns(
                vnic=[ns(
                    portgroup='Management Network',
                    spec=ns(
                        portgroup='Management Network',
                        ip=ns(ipAddress='192.0.2.10'),
                    ),
                )],
                pnic=[ns(
                    key='key-vim.host.PhysicalNic-vmnic0',
                    device='vmnic0',
                    mac='00:11:22:33:44:55',
                    linkSpeed=ns(speedMb=1000),
                )],
                portgroup=[
                    ns(spec=ns(
                        name='Management Network',
                        vlanId=0,
                        vswitchName='vSwitch0',
                    )),
                    ns(spec=ns(
                        name='VM Network',
                        vlanId=120,
                        vswitchName='vSwitch0',
                    )),
                ],
                vswitch=[ns(
                    name='vSwitch0',
                    pnic=['key-vim.host.PhysicalNic-vmnic0'],
                )],
            ),
            storageDevice=ns(scsiLun=[host_disk]),
            autoStart=ns(powerInfo=[ns(key=vm, startAction='powerOn')]),
        ),
        datastore=[datastore],
        vm=[vm],
    )
    return FakeEsxiService(host)
