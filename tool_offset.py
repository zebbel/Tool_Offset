# Nozzle alignment module for 3d kinematic probes.
#
# This module has been adapted from code written by Kevin O'Connor <kevin@koconnor.net> and Martin Hierholzer <martin@hierholzer.info>
# Sourced from https://github.com/ben5459/Klipper_ToolChanger/blob/master/probe_multi_axis.py

import logging

direction_types = {'x+': [0, +1], 'x-': [0, -1], 'y+': [1, +1], 'y-': [1, -1],
                   'z+': [2, +1], 'z-': [2, -1]}

HINT_TIMEOUT = """
If the probe did not move far enough to trigger, then
consider reducing/increasing the axis minimum/maximum
position so the probe can travel further (the minimum
position can be negative).
"""


class ToolsCalibrate:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.name = config.get_name()
        self.gcode_move = self.printer.load_object(config, "gcode_move")

        self.probe_multi_axis = PrinterProbeMultiAxis(config, 'probe_multi_axis', ProbeEndstopWrapper(config, 'x', config.get('pin')), ProbeEndstopWrapper(config, 'y', config.get('pin')), ProbeEndstopWrapper(config, 'z', config.get('pin')))
        self.bed_probe = PrinterProbeMultiAxis(config,'bed_probe', ProbeEndstopWrapper(config, 'x', config.get('pin')), ProbeEndstopWrapper(config, 'y', config.get('pin')), ProbeEndstopWrapper(config, 'z', config.get('bed_pin')))

        self.z_endstop_x_possition = config.getfloat('z_endstop_x_possition')
        self.z_endstop_y_possition = config.getfloat('z_endstop_y_possition')
        self.save_z_height = config.getfloat('save_z_height')
        self.tool_z_offset = None
        self.activ_tool = None
        self.position_z_endstop = config.getsection('stepper_z').getfloat('position_endstop', note_valid=False)

        self.bed_probe_trigger_offset = config.getfloat("bed_probe_trigger_offset", 0.0)

        self.probe_name = config.get('probe', 'probe')
        self.travel_speed = config.getfloat('travel_speed', 10.0, above=0.)
        self.spread = config.getfloat('spread', 5.0)
        self.lower_z = config.getfloat('lower_z', 0.5)
        self.lift_z = config.getfloat('lift_z', 1.0)
        self.trigger_to_bottom_z = config.getfloat('trigger_to_bottom_z', default=0.0)
        self.lift_speed = config.getfloat('lift_speed', self.probe_multi_axis.lift_speed)
        self.sensor_location = [config.getfloat('xy_probe_x_possition'), config.getfloat('xy_probe_y_possition'), config.getfloat('xy_probe_z_possition')]
        self.last_result = [0., 0., 0.]
        self.last_probe_offset = 0.

        # Register commands
        self.gcode = self.printer.lookup_object('gcode')

        self.gcode.register_command('TOOL_PROBE_Z_ENDSTOP', self.cmd_TOOL_PROBE_Z_ENDSTOP, desc=self.cmd_TOOL_PROBE_Z_ENDSTOP_help)
        self.gcode.register_command('TOOL_PROBE_BED', self.cmd_TOOL_PROBE_BED, desc=self.cmd_TOOL_PROBE_BED_help)
        self.gcode.register_command('TOOL_CALIBRATE_ENDSTOP_OFFSET', self.cmd_TOOL_CALIBRATE_ENDSTOP_OFFSET, desc=self.cmd_TOOL_CALIBRATE_ENDSTOP_OFFSET_help)
        self.gcode.register_command('TOOL_RESET_Z_ENDSTOP_OFFSET', self.cmd_TOOL_RESET_Z_ENDSTOP_OFFSET, desc=self.cmd_TOOL_RESET_Z_ENDSTOP_OFFSET_help)
        self.gcode.register_command('TOOL_LOCATE_SENSOR', self.cmd_TOOL_LOCATE_SENSOR, desc=self.cmd_TOOL_LOCATE_SENSOR_help)
        self.gcode.register_command('TOOL_CALIBRATE_TOOL_OFFSET', self.cmd_TOOL_CALIBRATE_TOOL_OFFSET, desc=self.cmd_TOOL_CALIBRATE_TOOL_OFFSET_help)
        self.gcode.register_command('TOOL_APPLY_TOOL_OFFSET', self.cmd_TOOL_APPLY_TOOL_OFFSET, desc=self.cmd_TOOL_APPLY_TOOL_OFFSET_help)
        self.gcode.register_command('TOOL_CALIBRATE_SAVE_TOOL_OFFSET', self.cmd_TOOL_CALIBRATE_SAVE_TOOL_OFFSET, desc=self.cmd_TOOL_CALIBRATE_SAVE_TOOL_OFFSET_help)
        self.gcode.register_command('TOOL_CALIBRATE_PROBE_OFFSET', self.cmd_TOOL_CALIBRATE_PROBE_OFFSET, desc=self.cmd_TOOL_CALIBRATE_PROBE_OFFSET_help)
    
    def probe_z(self, toolhead, top_pos, gcmd, samples=1):
        # move to endstop possition
        toolhead.manual_move([None, None, top_pos[2]], self.lift_speed)
        toolhead.manual_move([top_pos[0], top_pos[1], None], self.travel_speed)
        # probe
        curpos = self.probe_multi_axis.run_probe('z-', gcmd, speed_ratio=2.0, samples=samples)
        # retract
        toolhead.manual_move([None, None, curpos[2] + self.lift_z], self.lift_speed)
        # second probe
        curpos = self.probe_multi_axis.run_probe('z-', gcmd, samples=samples)
        # retract
        toolhead.manual_move([None, None, self.save_z_height], self.travel_speed)

        return curpos

    def probe_xy(self, toolhead, top_pos, direction, gcmd, samples=None):
        offset = direction_types[direction]
        start_pos = list(top_pos)
        start_pos[offset[0]] -= offset[1] * self.spread
        toolhead.manual_move([None, None, top_pos[2] + self.lift_z], self.lift_speed)
        toolhead.manual_move([start_pos[0], start_pos[1], None], self.travel_speed)

        toolhead.manual_move([None, None, top_pos[2] - self.lower_z], self.lift_speed)
        return self.probe_multi_axis.run_probe(direction, gcmd, samples=samples, max_distance=self.spread * 1.8)[offset[0]]
    
    def probe_bed(self, toolhead, top_pos, gcmd, samples=1):
        # move to endstop possition
        toolhead.manual_move([None, None, top_pos[2]], self.lift_speed)
        toolhead.manual_move([top_pos[0], top_pos[1], None], self.travel_speed)
        # probe
        curpos = self.bed_probe.run_probe('z-', gcmd, speed_ratio=2.0, samples=samples)
        # retract
        toolhead.manual_move([None, None, curpos[2] + self.lift_z], self.lift_speed)
        # second probe
        curpos = self.bed_probe.run_probe('z-', gcmd, samples=samples)

        return curpos

    def probe_xy_center(self, toolhead, top_pos, gcmd, samples=None):
        left_x = self.probe_xy(toolhead, top_pos, 'x+', gcmd, samples=samples)
        right_x = self.probe_xy(toolhead, top_pos, 'x-', gcmd, samples=samples)
        near_y = self.probe_xy(toolhead, top_pos, 'y+', gcmd, samples=samples)
        far_y = self.probe_xy(toolhead, top_pos, 'y-', gcmd, samples=samples)
        return [(left_x + right_x) / 2., (near_y + far_y) / 2.]
    
    def locate_sensor(self, toolhead, gcmd):
        self.activ_tool = self.printer.lookup_object('toolchanger').active_tool
        
        # sensor location in config is relativ to tool
        # homing uses absolute coordinat system
        corrected_xy_probe_z_possition = self.sensor_location[2] + self.tool_z_offset

        toolhead.manual_move([self.sensor_location[0], self.sensor_location[1], corrected_xy_probe_z_possition + self.lift_z], self.travel_speed)

        center_x, center_y = self.probe_xy_center(toolhead, [self.sensor_location[0], self.sensor_location[1], corrected_xy_probe_z_possition], gcmd, samples=1)
        toolhead.manual_move([None, None, corrected_xy_probe_z_possition + self.lift_z], self.lift_speed)
        toolhead.manual_move([center_x, center_y, None], self.travel_speed)

        # Now redo X and Y, since we have a more accurate center.
        center_x, center_y = self.probe_xy_center(toolhead, [center_x, center_y, corrected_xy_probe_z_possition], gcmd)
        # retract
        toolhead.manual_move([None, None, self.save_z_height], self.lift_speed)
        toolhead.manual_move([center_x, center_y, None], self.travel_speed)

        return [center_x, center_y, self.sensor_location[2]]

    cmd_TOOL_PROBE_Z_ENDSTOP_help = "probe Z endstop and return result"
    def cmd_TOOL_PROBE_Z_ENDSTOP(self, gcmd):
        toolhead = self.printer.lookup_object('toolhead')

        zepos = self.probe_z(toolhead, [self.z_endstop_x_possition, self.z_endstop_y_possition, self.save_z_height], gcmd)
        self.gcode.respond_info("%s: z endstop probe: %.6f" % (gcmd.get_command(), zepos[2]))

    cmd_TOOL_PROBE_BED_help = "probe bed and return result"
    def cmd_TOOL_PROBE_BED(self, gcmd):
        toolhead = self.printer.lookup_object('toolhead')

        zepos = self.probe_bed(toolhead, [175.0, 175.0, self.save_z_height], gcmd)
        self.gcode.respond_info("%s: bed probe result: %.6f" % (gcmd.get_command(), zepos[2]))
    
    cmd_TOOL_CALIBRATE_ENDSTOP_OFFSET_help = "calibrate offset from bed to Z endstop"
    def cmd_TOOL_CALIBRATE_ENDSTOP_OFFSET(self, gcmd):
        toolhead = self.printer.lookup_object('toolhead')
        bed_mesh = self.printer.lookup_object('bed_mesh')
        kin = toolhead.get_kinematics()

        epos = self.probe_bed(toolhead, [175.0, 175.0, self.save_z_height], gcmd)

        # zu untersuchen ob das nicht der direkter bzw einfachere weg ist
        #toolhead_position = self.gcode_move.get_status()['position']
        #gcode_position = self.gcode_move.get_status()['gcode_position']

        mesh_diff = epos[2] - bed_mesh.get_position()[2]
        self.gcode.respond_info("%s: mesh_diff: %.6f" % (gcmd.get_command(), mesh_diff))

        epos[2] = epos[2] + self.bed_probe_trigger_offset
        self.gcode.respond_info("%s: bed probe: %.6f" % (gcmd.get_command(), epos[2]))
        
        # retract
        toolhead.manual_move([None, None, self.save_z_height], self.travel_speed)

        # probe endstop
        zepos = self.probe_z(toolhead, [self.z_endstop_x_possition, self.z_endstop_y_possition, self.save_z_height], gcmd)
        self.gcode.respond_info("%s: z endstop probe: %.6f" % (gcmd.get_command(), zepos[2]))

        self.gcode.respond_info("%s: set z endstop possition to: %.6f" % (gcmd.get_command(), epos[2]-zepos[2]+mesh_diff))
        kin.rails[2].position_endstop = epos[2]-zepos[2]+mesh_diff

    cmd_TOOL_RESET_Z_ENDSTOP_OFFSET_help = ("Reset Z endstop possition to cfg value")
    def cmd_TOOL_RESET_Z_ENDSTOP_OFFSET(self, gcmd):
        toolhead = self.printer.lookup_object('toolhead')
        kin = toolhead.get_kinematics()
        kin.rails[2].position_endstop = self.position_z_endstop
        self.gcode.respond_info("%s: reset z endstop possition to: %.6f" % (gcmd.get_command(), self.position_z_endstop))

    cmd_TOOL_LOCATE_SENSOR_help = ("Locate the tool calibration sensor, use with tool 0.")
    def cmd_TOOL_LOCATE_SENSOR(self, gcmd):
        toolhead = self.printer.lookup_object('toolhead')
        self.gcode.run_script_from_command('G28')
        self.tool_z_offset = 0.0
        self.last_result = self.locate_sensor(toolhead, gcmd)
        self.sensor_location = self.last_result
        self.gcode.respond_info("%s: Sensor location at %.6f,%.6f,%.6f" % (gcmd.get_command(), self.last_result[0], self.last_result[1], self.last_result[2]))

    cmd_TOOL_CALIBRATE_TOOL_OFFSET_help = "Calibrate current tool offset relative to tool 0"
    def cmd_TOOL_CALIBRATE_TOOL_OFFSET(self, gcmd):
        if not self.sensor_location:
            raise gcmd.error("No recorded sensor location, please run TOOL_LOCATE_SENSOR first")
        
        toolhead = self.printer.lookup_object('toolhead')
        zOffset = self.probe_z(toolhead, [self.z_endstop_x_possition, self.z_endstop_y_possition, self.save_z_height], gcmd)[2]
        self.tool_z_offset = self.position_z_endstop + zOffset
        #self.gcode.respond_info("z offset:%.6f, self.position_z_endstop:%.6f, self.tool_z_offset:%.6f" % (zOffset, self.position_z_endstop, self.tool_z_offset))

        location = self.locate_sensor(toolhead, gcmd)
        self.last_result = [location[i] - self.sensor_location[i] for i in range(3)]
        self.last_result[2] = self.tool_z_offset

        self.gcode.respond_info("Tool offset is %.6f,%.6f,%.6f" % (self.last_result[0], self.last_result[1], self.last_result[2]))

    cmd_TOOL_APPLY_TOOL_OFFSET_help = "Apply offsets"
    def cmd_TOOL_APPLY_TOOL_OFFSET(self, gcmd):
        self.activ_tool.gcode_x_offset = self.last_result[0]
        self.activ_tool.gcode_y_offset = self.last_result[1]
        self.activ_tool.gcode_z_offset = self.last_result[2]
        self.gcode.run_script_from_command('_APPLY_ACTIVE_TOOL_GCODE_OFFSETS')

        self.gcode.respond_info("Tool offset applyed to tool: %s, offsets: %.6f,%.6f,%.6f" % (self.activ_tool.name, self.last_result[0], self.last_result[1], self.last_result[2]))

    cmd_TOOL_CALIBRATE_SAVE_TOOL_OFFSET_help = "Save tool offset calibration to config"
    def cmd_TOOL_CALIBRATE_SAVE_TOOL_OFFSET(self, gcmd):
        if not self.last_result:
            gcmd.error(
                "No offset result, please run TOOL_CALIBRATE_TOOL_OFFSET first")
            return
        section_name = gcmd.get("SECTION")
        param_name = gcmd.get("ATTRIBUTE")
        template = gcmd.get("VALUE", "{x:0.6f}, {y:0.6f}, {z:0.6f}")
        value = template.format(x=self.last_result[0], y=self.last_result[1],
                                z=self.last_result[2])
        configfile = self.printer.lookup_object('configfile')
        configfile.set(section_name, param_name, value)

    cmd_TOOL_CALIBRATE_PROBE_OFFSET_help = "Calibrate the tool probe offset to nozzle tip"
    def cmd_TOOL_CALIBRATE_PROBE_OFFSET(self, gcmd):
        toolhead = self.printer.lookup_object('toolhead')
        probe = self.printer.lookup_object(self.probe_name)
        start_pos = toolhead.get_position()
        nozzle_z = self.probe_multi_axis.run_probe("z-", gcmd, speed_ratio=0.5)[2]
        # now move down with the tool probe
        probe_session = probe.start_probe_session(gcmd)
        probe_session.run_probe(gcmd)
        probe_z = probe_session.pull_probed_results()[0][2]
        probe_session.end_probe_session()

        z_offset = probe_z - nozzle_z + self.trigger_to_bottom_z
        self.last_probe_offset = z_offset
        self.gcode.respond_info(
            "%s: z_offset: %.3f\n"
            "The SAVE_CONFIG command will update the printer config file\n"
            "with the above and restart the printer." % (
            self.probe_name, z_offset))
        config_name = gcmd.get("PROBE", default=self.probe_name)
        if config_name:
            configfile = self.printer.lookup_object('configfile')
            configfile.set(config_name, 'z_offset', "%.6f" % (z_offset,))
        # back to start pos
        toolhead.move(start_pos, self.travel_speed)
        toolhead.set_position(start_pos)

class PrinterProbeMultiAxis:
    def __init__(self, config, name, mcu_probe_x, mcu_probe_y, mcu_probe_z):
        self.printer = config.get_printer()
        self.name = config.get_name()
        self.mcu_probe = [mcu_probe_x, mcu_probe_y, mcu_probe_z]
        self.speed = config.getfloat('speed', 5.0, above=0.)
        self.lift_speed = config.getfloat('lift_speed', self.speed, above=0.)
        self.max_travel = config.getfloat("max_travel", 4, above=0)
        self.last_state = False
        self.last_result = [0., 0., 0.]
        self.last_x_result = 0.
        self.last_y_result = 0.
        self.last_z_result = 0.
        self.gcode = self.printer.lookup_object('gcode')
        self.gcode_move = self.printer.load_object(config, "gcode_move")

        # Multi-sample support (for improved accuracy)
        self.sample_count = config.getint('samples', 1, minval=1)
        self.sample_retract_dist = config.getfloat('sample_retract_dist', 2.,
                                                   above=0.)
        atypes = {'median': 'median', 'average': 'average'}
        self.samples_result = config.getchoice('samples_result', atypes,
                                               'average')
        self.samples_tolerance = config.getfloat('samples_tolerance', 0.100,
                                                 minval=0.)
        self.samples_retries = config.getint('samples_tolerance_retries', 0,
                                             minval=0)
        # Register xyz_virtual_endstop pin
        self.printer.lookup_object('pins').register_chip(name,
                                                         self)

    def setup_pin(self, pin_type, pin_params):
        if pin_type != 'endstop' or pin_params['pin'] != 'xy_virtual_endstop':
            raise pins.error("Probe virtual endstop only useful as endstop pin")
        if pin_params['invert'] or pin_params['pullup']:
            raise pins.error("Can not pullup/invert probe virtual endstop")
        return self.mcu_probe

    def get_lift_speed(self, gcmd=None):
        if gcmd is not None:
            return gcmd.get_float("LIFT_SPEED", self.lift_speed, above=0.)
        return self.lift_speed

    def _probe(self, speed, axis, sense, max_distance):
        phoming = self.printer.lookup_object('homing')
        pos = self._get_target_position(axis, sense, max_distance)
        try:
            epos = phoming.probing_move(self.mcu_probe[axis], pos, speed)
        except self.printer.command_error as e:
            reason = str(e)
            if "Timeout during endstop homing" in reason:
                reason += HINT_TIMEOUT
            raise self.printer.command_error(reason)
        # self.gcode.respond_info("probe at %.3f,%.3f is z=%.6f"
        self.gcode.respond_info("Probe made contact at %.6f,%.6f,%.6f"
                                % (epos[0], epos[1], epos[2]))
        return epos[:3]

    def _get_target_position(self, axis, sense, max_distance):
        toolhead = self.printer.lookup_object('toolhead')
        curtime = self.printer.get_reactor().monotonic()
        if 'x' not in toolhead.get_status(curtime)['homed_axes'] or \
                'y' not in toolhead.get_status(curtime)['homed_axes'] or \
                'z' not in toolhead.get_status(curtime)['homed_axes']:
            raise self.printer.command_error("Must home before probe")
        pos = toolhead.get_position()
        kin_status = toolhead.get_kinematics().get_status(curtime)
        if 'axis_minimum' not in kin_status or 'axis_minimum' not in kin_status:
            raise self.gcode.error(
                "Tools calibrate only works with cartesian kinematics")
        if sense > 0:
            pos[axis] = min(pos[axis] + max_distance,
                            kin_status['axis_maximum'][axis])
        else:
            pos[axis] = max(pos[axis] - max_distance,
                            kin_status['axis_minimum'][axis])
        return pos

    def _move(self, coord, speed):
        self.printer.lookup_object('toolhead').manual_move(coord, speed)

    def _calc_mean(self, positions):
        count = float(len(positions))
        return [sum([pos[i] for pos in positions]) / count
                for i in range(3)]

    def _calc_median(self, positions, axis):
        axis_sorted = sorted(positions, key=(lambda p: p[axis]))
        middle = len(positions) // 2
        if (len(positions) & 1) == 1:
            # odd number of samples
            return axis_sorted[middle]
        # even number of samples
        return self._calc_mean(axis_sorted[middle - 1:middle + 1])

    def run_probe(self, direction, gcmd, speed_ratio=1.0, samples=None,
                  max_distance=100.0):
        speed = gcmd.get_float("PROBE_SPEED", self.speed,
                               above=0.) * speed_ratio
        if direction not in direction_types:
            raise self.printer.command_error("Wrong value for DIRECTION.")

        logging.info("run_probe direction = %s" % (direction,))

        (axis, sense) = direction_types[direction]

        logging.info("run_probe axis = %d, sense = %d" % (axis, sense))

        lift_speed = self.get_lift_speed(gcmd)
        sample_count = gcmd.get_int("SAMPLES",
                                    samples if samples else self.sample_count,
                                    minval=1)
        sample_retract_dist = gcmd.get_float("SAMPLE_RETRACT_DIST",
                                             self.sample_retract_dist, above=0.)
        samples_tolerance = gcmd.get_float("SAMPLES_TOLERANCE",
                                           self.samples_tolerance, minval=0.)
        samples_retries = gcmd.get_int("SAMPLES_TOLERANCE_RETRIES",
                                       self.samples_retries, minval=0)
        samples_result = gcmd.get("SAMPLES_RESULT", self.samples_result)

        probe_start = self.printer.lookup_object('toolhead').get_position()
        retries = 0
        positions = []
        while len(positions) < sample_count:
            # Probe position
            pos = self._probe(speed, axis, sense, max_distance)
            positions.append(pos)
            # Check samples tolerance
            axis_positions = [p[axis] for p in positions]
            if max(axis_positions) - min(axis_positions) > samples_tolerance:
                if retries >= samples_retries:
                    raise gcmd.error("Probe samples exceed samples_tolerance")
                gcmd.respond_info("Probe samples exceed tolerance. Retrying...")
                retries += 1
                positions = []
            # Retract
            if len(positions) < sample_count:
                liftpos = probe_start
                liftpos[axis] = pos[axis] - sense * sample_retract_dist
                self._move(liftpos, lift_speed)
        # Calculate and return result
        if samples_result == 'median':
            return self._calc_median(positions, axis)
        return self._calc_mean(positions)

# Endstop wrapper that enables probe specific features
class ProbeEndstopWrapper:
    def __init__(self, config, axis, pin):
        self.printer = config.get_printer()
        self.axis = axis
        self.idex = config.has_section('dual_carriage')
        # Create an "endstop" object to handle the probe pin
        ppins = self.printer.lookup_object('pins')
        ppins.allow_multi_use_pin(pin.replace('^', '').replace('!', ''))
        pin_params = ppins.lookup_pin(pin, can_invert=True, can_pullup=True)
        mcu = pin_params['chip']
        self.mcu_endstop = mcu.setup_pin('endstop', pin_params)
        self.printer.register_event_handler('klippy:mcu_identify',
                                            self._handle_mcu_identify)
        # Wrappers
        self.get_mcu = self.mcu_endstop.get_mcu
        self.add_stepper = self.mcu_endstop.add_stepper
        self.get_steppers = self._get_steppers
        self.home_start = self.mcu_endstop.home_start
        self.home_wait = self.mcu_endstop.home_wait
        self.query_endstop = self.mcu_endstop.query_endstop

    def _get_steppers(self):
        if self.idex and self.axis == 'x':
            dual_carriage = self.printer.lookup_object('dual_carriage')
            prime_rail = dual_carriage.get_primary_rail()
            return prime_rail.get_rail().get_steppers()
        else:
            return self.mcu_endstop.get_steppers()

    def _handle_mcu_identify(self):
        kin = self.printer.lookup_object('toolhead').get_kinematics()
        for stepper in kin.get_steppers():
            if stepper.is_active_axis(self.axis):
                self.add_stepper(stepper)

    def get_position_endstop(self):
        return 0.


def load_config(config):
    return ToolsCalibrate(config)