// SPDX-License-Identifier: GPL-2.0-or-later
/*
 * gigactl_hotkeys.c - Bridge WMI hotkeys de teclado para laptops Gigabyte G5/G6/G7 (Clevo ODM).
 *
 * Activa el reenvio de eventos WMI (WMBB 0x46) y traduce los codigos Fn de
 * iluminacion del teclado en eventos estandar del subsistema input de Linux.
 * No escribe ningun registro LED del EC para no competir con gigactld.
 */

#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/acpi.h>
#include <linux/dmi.h>
#include <linux/input.h>
#include <linux/input/sparse-keymap.h>
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/version.h>
#include <linux/wmi.h>

#define CLEVO_EVENT_GUID "ABBC0F6B-8EA1-11D1-00A0-C90629100000"
#define CLEVO_WMBB_GUID  "ABBC0F6D-8EA1-11D1-00A0-C90629100000"

#define WMBB_GET_EVENT   0x01
#define WMBB_SET_HOTKEYS 0x46

static bool force;
module_param(force, bool, 0444);
MODULE_PARM_DESC(force, "Cargar sin verificar DMI Gigabyte G5/G6/G7");

struct gigactl_hotkeys_data {
	struct input_dev *input;
};

static const struct key_entry gigactl_keymap[] = {
	/* White-only keyboard events */
	{ KE_KEY, 0x20, { KEY_KBDILLUMDOWN } },
	{ KE_KEY, 0x21, { KEY_KBDILLUMUP } },
	{ KE_KEY, 0x3f, { KEY_KBDILLUMTOGGLE } },

	/* RGB keyboard events */
	{ KE_KEY, 0x81, { KEY_KBDILLUMDOWN } },
	{ KE_KEY, 0x82, { KEY_KBDILLUMUP } },
	{ KE_KEY, 0x83, { KEY_PROG1 } },
	{ KE_KEY, 0x9f, { KEY_KBDILLUMTOGGLE } },
	{ KE_END }
};

static const struct dmi_system_id gigactl_dmi_table[] = {
	{
		.ident = "GIGABYTE G5",
		.matches = {
			DMI_MATCH(DMI_SYS_VENDOR, "GIGABYTE"),
			DMI_MATCH(DMI_PRODUCT_NAME, "G5"),
		},
	},
	{
		.ident = "GIGABYTE G6",
		.matches = {
			DMI_MATCH(DMI_SYS_VENDOR, "GIGABYTE"),
			DMI_MATCH(DMI_PRODUCT_NAME, "G6"),
		},
	},
	{
		.ident = "GIGABYTE G7",
		.matches = {
			DMI_MATCH(DMI_SYS_VENDOR, "GIGABYTE"),
			DMI_MATCH(DMI_PRODUCT_NAME, "G7"),
		},
	},
	{ }
};
MODULE_DEVICE_TABLE(dmi, gigactl_dmi_table);

static int clevo_wmbb(u32 method_id, u32 arg, u32 *retval)
{
	struct acpi_buffer in = { (acpi_size)sizeof(arg), &arg };
	struct acpi_buffer out = { ACPI_ALLOCATE_BUFFER, NULL };
	union acpi_object *obj;
	acpi_status status;
	u32 tmp = 0;

	status = wmi_evaluate_method(CLEVO_WMBB_GUID, 0, method_id, &in, &out);
	if (ACPI_FAILURE(status))
		return -EIO;

	obj = out.pointer;
	if (obj && obj->type == ACPI_TYPE_INTEGER)
		tmp = (u32)obj->integer.value;

	if (retval)
		*retval = tmp;

	kfree(obj);
	return 0;
}

static void gigactl_handle_event(struct gigactl_hotkeys_data *priv)
{
	u32 event = 0;

	if (clevo_wmbb(WMBB_GET_EVENT, 0, &event) != 0)
		return;

	pr_debug("WMI event 0x%02x\n", event);
	sparse_keymap_report_event(priv->input, event, 1, true);
}

static void gigactl_wmi_notify_new(struct wmi_device *wdev, const struct wmi_buffer *data)
{
	struct gigactl_hotkeys_data *priv = dev_get_drvdata(&wdev->dev);

	(void)data;
	if (priv)
		gigactl_handle_event(priv);
}

static int gigactl_wmi_probe(struct wmi_device *wdev, const void *context)
{
	struct gigactl_hotkeys_data *priv;
	struct input_dev *input;
	int err;

	(void)context;

	if (!force && !dmi_check_system(gigactl_dmi_table)) {
		pr_info("Hardware fuera de rango Gigabyte G5/G6/G7 (usa force=1 para forzar)\n");
		return -ENODEV;
	}

	priv = devm_kzalloc(&wdev->dev, sizeof(*priv), GFP_KERNEL);
	if (!priv)
		return -ENOMEM;

	input = devm_input_allocate_device(&wdev->dev);
	if (!input)
		return -ENOMEM;

	input->name = "Gigabyte Clevo Hotkeys";
	input->phys = "gigactl-hotkeys/input0";
	input->id.bustype = BUS_HOST;
	input->dev.parent = &wdev->dev;

	err = sparse_keymap_setup(input, gigactl_keymap, NULL);
	if (err)
		return err;

	err = input_register_device(input);
	if (err)
		return err;

	priv->input = input;
	dev_set_drvdata(&wdev->dev, priv);

	/* Habilitar reenvio de eventos Fn desde el EC/BIOS */
	if (clevo_wmbb(WMBB_SET_HOTKEYS, 0, NULL) != 0)
		pr_warn("WMBB(0x46) devolvio error al habilitar eventos\n");

	pr_info("Bridge de teclas Fn de iluminacion activo\n");
	return 0;
}

static int gigactl_wmi_resume(struct device *dev)
{
	(void)dev;
	(void)clevo_wmbb(WMBB_SET_HOTKEYS, 0, NULL);
	return 0;
}

static DEFINE_SIMPLE_DEV_PM_OPS(gigactl_hotkeys_pm, NULL, gigactl_wmi_resume);

static const struct wmi_device_id gigactl_wmi_id_table[] = {
	{ .guid_string = CLEVO_EVENT_GUID },
	{ }
};
MODULE_DEVICE_TABLE(wmi, gigactl_wmi_id_table);

static struct wmi_driver gigactl_wmi_driver = {
	.driver = {
		.name = "gigactl-hotkeys",
		.pm = pm_sleep_ptr(&gigactl_hotkeys_pm),
	},
	.id_table = gigactl_wmi_id_table,
	.min_event_size = 0,
	.probe = gigactl_wmi_probe,
	.notify_new = gigactl_wmi_notify_new,
};
module_wmi_driver(gigactl_wmi_driver);

MODULE_AUTHOR("Benjamin / GigaControl Center");
MODULE_DESCRIPTION("WMI Fn hotkey bridge for Gigabyte G5/G6/G7 Clevo-ODM laptops");
MODULE_LICENSE("GPL");
MODULE_VERSION("1.0.0");
