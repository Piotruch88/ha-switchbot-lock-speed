"""Renaming the device / entity ID must keep the entity available."""
from homeassistant.helpers import device_registry as dr, entity_registry as er

from test_integration import ENTITY, setup, key, lock, ble, bluetooth_loaded  # noqa: F401


async def test_rename_device_and_entity_id(hass, key, lock, ble):
    entry = await setup(hass, key)
    assert hass.states.get(ENTITY).state == "max"
    ent_reg, dev_reg = er.async_get(hass), dr.async_get(hass)
    device = dev_reg.async_get(ent_reg.async_get(ENTITY).device_id)
    dev_reg.async_update_device(device.id, name_by_user="Front door lock (renamed)")
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == "max", "device rename"
    new_id = "select.front_door_lock_renamed_motor_speed"
    ent_reg.async_update_entity(ENTITY, new_entity_id=new_id)
    await hass.async_block_till_done()
    print("old:", hass.states.get(ENTITY), "\nnew:", hass.states.get(new_id))
    assert hass.states.get(new_id).state == "max", "entity id rename"
