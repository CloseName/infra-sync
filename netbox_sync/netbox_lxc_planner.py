import json

from .netbox_lxc_metadata import (
    MANAGED_LXC_CUSTOM_FIELDS,
    build_lxc_custom_fields,
    find_lxc_sync_identity_matches,
    lxc_identity_source_id,
)


def _status(value):
    mapping = {
        'running': 'active',
        'stopped': 'offline',
        'paused': 'paused',
    }

    if value not in mapping:
        raise RuntimeError(
            f'Unsupported LXC status: '
            f'{value!r}'
        )

    return mapping[value]


def _disk_mib(container):
    return sum(
        disk.size_bytes
        for disk in container.disks
    ) // 1024**2


def plan_lxc_containers(
        nb_api,
        host,
        cluster,
):
    print()
    print(
        '  LXC CONTAINERS'
    )

    existing_vms = list(
        nb_api.virtualization
        .virtual_machines
        .filter(
            cluster_id=cluster.id
        )
    )

    counters = {
        'match': 0,
        'create': 0,
        'adopt_candidate': 0,
        'conflict': 0,
    }

    for container in sorted(
        host.containers,
        key=lambda item: item.vmid,
    ):
        identity_matches = find_lxc_sync_identity_matches(
            existing_vms, container,
        )

        if len(identity_matches) > 1:
            counters[
                'conflict'
            ] += 1

            print(
                f'    CONFLICT LXC '
                f'vmid={container.vmid} '
                f'name={container.original_name!r} '
                f'reason=duplicate_identity'
            )

            continue

        existing = None

        if len(identity_matches) == 1:
            existing = (
                identity_matches[0]
            )

            counters[
                'match'
            ] += 1

            print(
                f'    MATCH LXC '
                f'id={existing.id} '
                f'vmid={container.vmid} '
                f'name={container.original_name!r} '
                f'reason=sync_identity'
            )

        else:
            name_matches = [
                candidate
                for candidate
                in existing_vms
                if (
                    candidate.name.casefold()
                    == container.original_name.casefold()
                    and getattr(
                        candidate,
                        'tenant',
                        None,
                    ) is None
                )
            ]

            if len(name_matches) > 1:
                counters[
                    'conflict'
                ] += 1

                print(
                    f'    CONFLICT LXC '
                    f'vmid={container.vmid} '
                    f'name={container.original_name!r} '
                    f'reason=duplicate_name'
                )

                continue

            if len(name_matches) == 1:
                counters[
                    'adopt_candidate'
                ] += 1

                print(
                    f'    ADOPT CANDIDATE '
                    f'LXC vmid='
                    f'{container.vmid} '
                    f'name='
                    f'{container.original_name!r} '
                    f'action=not-adopted'
                )

                existing = (
                    name_matches[0]
                )
            else:
                counters[
                    'create'
                ] += 1

                print(
                    f'    CREATE LXC '
                    f'vmid={container.vmid} '
                    f'name='
                    f'{container.original_name!r}'
                )

        print(
            f'      identity='
            f'{container.source}:'
            f'{lxc_identity_source_id(container)}'
        )

        print(
            f'      cluster={cluster.name}'
        )

        print(
            f'      status='
            f'{_status(container.status)}'
        )

        print(
            f'      vcpus='
            f'{container.vcpus}'
        )

        print(
            f'      memory_mib='
            f'{container.memory_bytes // 1024**2}'
        )

        print(
            f'      swap_mib='
            f'{container.swap_bytes // 1024**2}'
        )

        print(
            f'      disk_mib='
            f'{_disk_mib(container)}'
        )

        print(
            f'      architecture='
            f'{container.architecture}'
        )

        print(
            f'      os_type='
            f'{container.os_type}'
        )

        print(
            f'      start_on_boot='
            f'{"on" if container.autostart else "off"}'
        )

        current_cf = {}

        if existing is not None:
            current_cf = dict(
                getattr(
                    existing,
                    'custom_fields',
                    None,
                )
                or {}
            )

        desired_cf = (
            build_lxc_custom_fields(
                container,
                current_cf,
            )
        )

        print(
            '      managed_custom_fields:'
        )

        for field_name in (
            MANAGED_LXC_CUSTOM_FIELDS
        ):
            action = (
                'KEEP'
                if current_cf.get(
                    field_name
                )
                == desired_cf.get(
                    field_name
                )
                else 'SET'
            )

            print(
                f'        {action} '
                f'{field_name}='
                + json.dumps(
                    desired_cf.get(
                        field_name
                    ),
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )

    print()
    print(
        '    LXC PLAN SUMMARY'
    )

    for key in (
        'match',
        'create',
        'adopt_candidate',
        'conflict',
    ):
        print(
            f'      {key}='
            f'{counters[key]}'
        )
