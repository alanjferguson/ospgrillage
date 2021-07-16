# ----------------------------------------------------------------------------------------------------------------
# Mesh class
# ----------------------------------------------------------------------------------------------------------------
from static import *
from collections import namedtuple

# named tuple definition
Point = namedtuple("Point", ['x', 'y', 'z'])


class Mesh:
    """
    Class for mesh groups. The class holds information pertaining the mesh group such as element connectivity and nodes
    of the mesh object.

    """

    def __init__(self, long_dim, width, trans_dim, edge_width, num_trans_beam, num_long_beam, skew_1, skew_2,
                 orthogonal=False, pt1=Point(0, 0, 0), pt2=Point(0, 0, 0), pt3=None, element_counter=1, node_counter=1,
                 transform_counter=0, global_x_grid_count=0, global_edge_count=0, mesh_origin=[0, 0, 0],
                 quad_ele=False):
        # inputs from OpsGrillage required to create mesh
        self.long_dim = long_dim
        self.trans_dim = trans_dim
        self.edge_width = edge_width
        self.width = width
        self.num_trans_beam = num_trans_beam
        self.num_long_beam = num_long_beam
        # angle and mesh type
        self.skew_1 = skew_1
        self.skew_2 = skew_2
        self.orthogonal = orthogonal
        # sweep path properties
        self.pt1 = pt1
        self.pt2 = pt2
        self.pt3 = pt3

        # counters to keep track of variables
        self.node_counter = node_counter
        self.element_counter = element_counter
        self.transform_counter = transform_counter
        self.global_x_grid_count = global_x_grid_count
        # edge construction line variables
        self.global_edge_count = global_edge_count
        self.edge_node_recorder = dict()  # key: node tag, val: unique tag for edge
        # Prefix/ rules variables here
        assigned_node_tag = []
        self.decimal_lim = 3  # variable for floating point arithmetic error
        self.skew_threshold = [11, 30]
        self.curve = False
        self.search_x_inc = 0.001
        # initiate list for nodes and elements
        self.long_ele = []
        self.trans_ele = []
        self.edge_span_ele = []

        self.y_elevation = 0
        self.mesh_design_line = []
        # dict for node and ele transform
        self.transform_dict = dict()  # key: vector xz, val: transform tag
        self.node_spec = dict()  # key: node tag, val: dict of node details - see technical notes
        # variables for curve mesh
        self.curve_center = []
        self.curve_radius = []
        # line / circle equation variables
        self.m = 0
        self.c = 0
        self.r = 0
        self.R = 0
        self.d = None  # list of circle centre and circle radius [ c, r]
        # meshing properties
        self.mesh_origin = mesh_origin  # default origin
        # meshing variables
        self.first_connecting_region_nodes = []
        self.end_connecting_region_nodes = []
        self.sweep_nodes = []
        self.z_group_recorder = []
        # quad elements flag
        self.quad_ele = quad_ele
        # ------------------------------------------------------------------------------------------

        # Create sweep path obj
        self.sweep_path = SweepPath(self.pt1, self.pt2, self.pt3)
        self.zeta, self.m, self.c = self.sweep_path.get_sweep_line_properties()
        # check condition for orthogonal mesh
        # self.__check_skew(self.zeta)
        # ------------------------------------------------------------------------------------------
        # edge construction line 1
        self.start_edge_line = EdgeConstructionLine(edge_ref_point=self.mesh_origin, width_z=self.width,
                                                    edge_width_z=self.edge_width, edge_angle=self.skew_1,
                                                    num_long_beam=self.num_long_beam, model_plane_y=self.y_elevation)

        # ------------------------------------------------------------------------------------------
        # edge construction line 2
        end_point_z = self.sweep_path.get_line_function(self.long_dim)

        self.end_edge_line = EdgeConstructionLine(edge_ref_point=[self.long_dim, 0, end_point_z], width_z=self.width,
                                                  edge_width_z=self.edge_width, edge_angle=self.skew_2,
                                                  num_long_beam=self.num_long_beam, model_plane_y=self.y_elevation)
        # ------------------------------------------------------------------------------------------
        # Sweep nodes
        # nodes to be swept across sweep path varies based
        # sweeping_nodes variable is a list containing x,y,z coordinates which slope is dependant on slope at  ref point
        # of sweep nodes. slope of sweep nodes is always ORTHOGONAL to tangent of sweep path at intersection with ref
        # point
        self.sweeping_nodes = []
        # z coordinate of ref sweep nodes (relative to origin)
        self.noz = self.start_edge_line.noz
        if orthogonal:
            self.sweeping_nodes = self.__rotate_sweep_nodes(self.zeta / 180 * np.pi)  # zeta in rad
        else:  # skew
            # sweep line of skew mesh == edge_construction line
            self.sweeping_nodes = self.start_edge_line.node_list
        self.nox = np.linspace(0, self.long_dim, self.num_trans_beam)
        # ------------------------------------------------------------------------------------------
        # create nodes and elements
        # if orthogonal, orthogonal mesh only be splayed onto a curve mesh, if skew mesh curved/arc line segment must be
        # false
        if self.orthogonal:
            # mesh start span construction line region
            self.__orthogonal_meshing()

        elif not self.curve:  # Skew mesh + angle
            self.__fixed_sweep_node_meshing()

        # run section grouping for longitudinal and transverse members
        self.__identify_member_groups()

    def __fixed_sweep_node_meshing(self):
        assigned_node_tag = []
        previous_node_tag = []
        for x_count, x_inc in enumerate(self.nox):
            for z_count, ref_point in enumerate(self.sweeping_nodes):
                # offset x and y in all points in ref points
                z_inc = np.round(
                    select_segment_function(curve_flag=self.curve, d=self.d, m=self.m, c=self.m, x=x_inc, r=self.r),
                    self.decimal_lim)
                node_coordinate = [ref_point[0] + x_inc, ref_point[1], ref_point[2] + z_inc]
                self.node_spec.setdefault(self.node_counter,
                                          {'tag': self.node_counter, 'coordinate': node_coordinate,
                                           'x_group': x_count, 'z_group': z_count})
                assigned_node_tag.append(self.node_counter)
                self.node_counter += 1
                # link transverse elements
                if z_count > 0:
                    # element list [element tag, node i, node j, x/z group]
                    tag = self.__get_geo_transform_tag([assigned_node_tag[z_count - 1], assigned_node_tag[z_count]])
                    self.trans_ele.append([self.element_counter, assigned_node_tag[z_count - 1],
                                           assigned_node_tag[z_count], x_count, tag])
                    self.element_counter += 1

            # link longitudinal elements
            if x_count == 0:
                previous_node_tag = assigned_node_tag
                # record
                for nodes in previous_node_tag:
                    self.edge_node_recorder.setdefault(nodes, self.global_edge_count)
                self.global_edge_count += 1
            elif x_count > 0:
                for pre_node in previous_node_tag:
                    for cur_node in assigned_node_tag:
                        cur_z_group = self.node_spec[cur_node]['z_group']
                        prev_z_group = self.node_spec[pre_node]['z_group']
                        if cur_z_group == prev_z_group:
                            tag = self.__get_geo_transform_tag([pre_node, cur_node])
                            self.long_ele.append([self.element_counter, pre_node, cur_node, cur_z_group, tag])
                            self.element_counter += 1
                            break  # break assign long ele loop (cur node)
                # update record for previous node tag step
                previous_node_tag = assigned_node_tag
                if x_count == len(self.nox) - 1:
                    for nodes in previous_node_tag:
                        self.edge_node_recorder.setdefault(nodes, self.global_edge_count)
                    self.global_edge_count += 1
            # reset counter for next loop

            assigned_node_tag = []
        print("Meshing completed....")

    def __orthogonal_meshing(self):
        global sweep_nodes, z_group_recorder
        self.assigned_node_tag = []
        self.previous_node_tag = []
        self.sweep_path_points = []
        # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
        # first edge construction line
        # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
        start_point_x = self.mesh_origin[0]
        start_point_z = self.mesh_origin[2]
        # if skew angle of edge line is below threshold for orthogonal,
        if np.abs(self.skew_1 + self.zeta) < self.skew_threshold[0]:
            # if angle less than threshold, assign nodes of edge member as it is
            current_sweep_nodes = self.start_edge_line.node_list
            for (z_count_int, nodes) in enumerate(current_sweep_nodes):
                x_inc = start_point_x
                z_inc = start_point_z
                node_coordinate = [nodes[0] + x_inc, nodes[1], nodes[2] + z_inc]
                self.node_spec.setdefault(self.node_counter, {'tag': self.node_counter, 'coordinate': node_coordinate,
                                                              'x_group': self.global_x_grid_count,
                                                              'z_group': z_count_int})

                self.assigned_node_tag.append(self.node_counter)
                self.node_counter += 1
                # if loop assigned more than two nodes, link nodes as a transverse member
                if z_count_int > 0:
                    # run sub procedure to assign
                    # self.__assign_transverse_members(pre_node=self.assigned_node_tag[z_count_int - 1],
                    #                                  cur_node=self.assigned_node_tag[z_count_int])

                    if len(self.assigned_node_tag) >= 1:
                        self.__assign_edge_trans_members(self.assigned_node_tag[z_count_int - 1],
                                                         self.assigned_node_tag[z_count_int],
                                                         self.global_edge_count)
                        # get and link edge nodes from previous and current as skewed edge member
                        self.edge_node_recorder.setdefault(self.assigned_node_tag[z_count_int - 1],
                                                           self.global_edge_count)
                        self.edge_node_recorder.setdefault(self.assigned_node_tag[z_count_int], self.global_edge_count)

                if len(self.assigned_node_tag) == len(self.noz):
                    self.first_connecting_region_nodes = self.assigned_node_tag
            self.global_x_grid_count += 1
            self.assigned_node_tag = []  # reset variable
            print("Edge mesh @ start span completed")
        else:
            # loop for each intersection point of edge line with sweep nodes
            for z_count, int_point in enumerate(self.start_edge_line.node_list):
                # search point on sweep path line whose normal intersects int_point.
                ref_point_x, ref_point_z = self.__search_x_point(int_point, start_point_x)
                # record points
                self.sweep_path_points.append([ref_point_x, self.y_elevation, ref_point_z])
                # find m' of line between intersect int_point and ref point on sweep path
                m_prime, phi = get_slope([ref_point_x, self.y_elevation, ref_point_z], int_point)
                # rotate sweep line such that parallel to m' line
                # if skew is positive, algorithm may mistake first point as orthogonal 90 deg, specify initial m based
                # on zeta
                if self.skew_1 > 0:
                    angle = np.arctan(self.zeta / 180 * np.pi)
                else:
                    angle = np.pi / 2 - np.abs(phi)
                current_sweep_nodes = self.__rotate_sweep_nodes(angle)
                # get z group of first node in current_sweep_nodes - for correct assignment in loop
                z_group = self.start_edge_line.get_node_group_z(int_point)
                # check
                # condition
                if 90 + self.skew_1 + self.zeta > 90:
                    sweep_nodes = current_sweep_nodes[z_count:]
                    z_group_recorder = list(range(z_group, len(current_sweep_nodes)))
                elif 90 + self.skew_1 + self.zeta < 90:
                    sweep_nodes = current_sweep_nodes[0:(z_count + 1)]
                    z_group_recorder = list(range(0, z_group + 1)) if z_group != 0 else [0]

                for (z_count_int, nodes) in enumerate(sweep_nodes):
                    x_inc = ref_point_x
                    z_inc = ref_point_z
                    node_coordinate = [nodes[0] + x_inc, nodes[1], nodes[2] + z_inc]
                    self.node_spec.setdefault(self.node_counter,
                                              {'tag': self.node_counter, 'coordinate': node_coordinate,
                                               'x_group': self.global_x_grid_count,
                                               'z_group': z_group_recorder[z_count_int]})

                    self.assigned_node_tag.append(self.node_counter)
                    self.node_counter += 1
                    # if loop assigned more than two nodes, link nodes as a transverse member
                    if z_count_int > 0:
                        # run sub procedure to assign
                        self.__assign_transverse_members(pre_node=self.assigned_node_tag[z_count_int - 1],
                                                         cur_node=self.assigned_node_tag[z_count_int])

                # if loop is in first step, there is only one column of nodes, skip longitudinal assignment
                if z_count == 0:
                    self.previous_node_tag = self.assigned_node_tag
                if z_count > 0:
                    for pre_node in self.previous_node_tag:
                        for cur_node in self.assigned_node_tag:
                            cur_z_group = self.node_spec[cur_node]['z_group']
                            prev_z_group = self.node_spec[pre_node]['z_group']
                            if cur_z_group == prev_z_group:
                                self.__assign_longitudinal_members(pre_node=pre_node, cur_node=cur_node,
                                                                   cur_z_group=cur_z_group)
                                break  # break assign long ele loop (cur node)

                    # if angle is positive (slope negative), edge nodes located at the first element of list
                    if len(self.assigned_node_tag) >= 1:
                        if 90 + self.skew_1 + self.zeta > 90:
                            self.__assign_edge_trans_members(self.previous_node_tag[0], self.assigned_node_tag[0],
                                                             self.global_edge_count)
                            # get and link edge nodes from previous and current as skewed edge member
                            self.edge_node_recorder.setdefault(self.previous_node_tag[0], self.global_edge_count)
                            self.edge_node_recorder.setdefault(self.assigned_node_tag[0], self.global_edge_count)
                        elif 90 + self.skew_1 + self.zeta < 90:
                            self.__assign_edge_trans_members(self.previous_node_tag[-1], self.assigned_node_tag[-1],
                                                             self.global_edge_count)
                            # get and link edge nodes from previous and current as skewed edge member
                            self.edge_node_recorder.setdefault(self.previous_node_tag[-1], self.global_edge_count)
                            self.edge_node_recorder.setdefault(self.assigned_node_tag[-1], self.global_edge_count)
                    # update recorder for previous node tag step
                    self.previous_node_tag = self.assigned_node_tag
                # update and reset recorders for next column of sweep nodes
                self.global_x_grid_count += 1
                if len(self.assigned_node_tag) == len(self.noz):
                    self.first_connecting_region_nodes = self.assigned_node_tag
                self.ortho_previous_node_column = self.assigned_node_tag
                self.assigned_node_tag = []
            self.global_edge_count += 1
            print("Edge mesh @ start span completed")
        # --------------------------------------------------------------------------------------------
        # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
        # second edge construction line
        # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
        # get end point of sweep line = point which sweep path intersects end span construction line
        end_point_x = self.long_dim
        # end_point_z = line_func(self.sweep_path.m,self.sweep_path.c,end_point_x)
        end_point_z = self.sweep_path.get_line_function(end_point_x)
        if np.abs(self.skew_2 + self.zeta) < self.skew_threshold[0]:
            # if angle less than threshold, assign nodes of edge member as it is
            current_sweep_nodes = self.end_edge_line.node_list
            for (z_count_int, nodes) in enumerate(current_sweep_nodes):
                x_inc = 0  # end_point_x
                z_inc = 0  # end_point_z
                node_coordinate = [nodes[0] + x_inc, nodes[1], nodes[2] + z_inc]
                self.node_spec.setdefault(self.node_counter, {'tag': self.node_counter, 'coordinate': node_coordinate,
                                                              'x_group': self.global_x_grid_count,
                                                              'z_group': z_count_int})

                self.assigned_node_tag.append(self.node_counter)
                self.node_counter += 1
                # if loop assigned more than two nodes, link nodes as a transverse member
                if z_count_int > 0:
                    # run sub procedure to assign
                    # self.__assign_transverse_members(pre_node=self.assigned_node_tag[z_count_int - 1],
                    #                                  cur_node=self.assigned_node_tag[z_count_int])
                    if len(self.assigned_node_tag) >= 1:
                        self.__assign_edge_trans_members(self.assigned_node_tag[z_count_int - 1],
                                                         self.assigned_node_tag[z_count_int],
                                                         self.global_edge_count)
                        # get and link edge nodes from previous and current as skewed edge member
                        self.edge_node_recorder.setdefault(self.assigned_node_tag[z_count_int - 1],
                                                           self.global_edge_count)
                        self.edge_node_recorder.setdefault(self.assigned_node_tag[z_count_int], self.global_edge_count)
                # self.end_connecting_region_nodes = self.assigned_node_tag
                if len(self.assigned_node_tag) == len(self.noz):
                    self.end_connecting_region_nodes = self.assigned_node_tag
            self.global_x_grid_count += 1
        else:
            for z_count, int_point in enumerate(self.end_edge_line.node_list):
                # search point on sweep path line whose normal intersects int_point.
                ref_point_x, ref_point_z = self.__search_x_point(int_point, start_point_x)
                # record points
                self.sweep_path_points.append([ref_point_x, self.y_elevation, ref_point_z])
                # find m' of line between intersect int_point and ref point on sweep path
                m_prime, phi = get_slope([ref_point_x, self.y_elevation, ref_point_z], int_point)
                # rotate sweep line such that parallel to m' line
                current_sweep_nodes = self.__rotate_sweep_nodes(np.pi / 2 - np.abs(phi))
                # get z group of first node in current_sweep_nodes - for correct assignment in loop
                z_group = self.end_edge_line.get_node_group_z(int_point)  # extract from class EdgeConstructionLine
                # check
                # condition
                if 90 + self.skew_2 + self.zeta > 90:
                    sweep_nodes = current_sweep_nodes[0:(z_count + 1)]
                    z_group_recorder = list(range(0, z_group + 1)) if z_group != 0 else [0]
                elif 90 + self.skew_2 + self.zeta < 90:
                    sweep_nodes = current_sweep_nodes[z_count:]
                    z_group_recorder = list(range(z_group, len(current_sweep_nodes)))
                for (z_count_int, nodes) in enumerate(sweep_nodes):
                    x_inc = ref_point_x
                    z_inc = ref_point_z
                    node_coordinate = [nodes[0] + x_inc, nodes[1], nodes[2] + z_inc]
                    self.node_spec.setdefault(self.node_counter,
                                              {'tag': self.node_counter, 'coordinate': node_coordinate,
                                               'x_group': self.global_x_grid_count,
                                               'z_group': z_group_recorder[z_count_int]})

                    self.assigned_node_tag.append(self.node_counter)
                    self.node_counter += 1
                    # if loop assigned more than two nodes, link nodes as a transverse member
                    if z_count_int > 0:
                        # run sub procedure to assign
                        self.__assign_transverse_members(pre_node=self.assigned_node_tag[z_count_int - 1],
                                                         cur_node=self.assigned_node_tag[z_count_int])

                # if loop is in first step, there is only one column of nodes, skip longitudinal assignment
                if z_count == 0:
                    self.previous_node_tag = self.assigned_node_tag
                if z_count > 0:
                    for pre_node in self.previous_node_tag:
                        for cur_node in self.assigned_node_tag:
                            cur_z_group = self.node_spec[cur_node]['z_group']
                            prev_z_group = self.node_spec[pre_node]['z_group']
                            if cur_z_group == prev_z_group:
                                self.__assign_longitudinal_members(pre_node=pre_node, cur_node=cur_node,
                                                                   cur_z_group=cur_z_group)
                                break  # break assign long ele loop (cur node)

                    # if angle is positive (slope negative), edge nodes located at the first element of list
                    if len(self.assigned_node_tag) >= 1:
                        if 90 + self.skew_2 + self.zeta > 90:
                            self.__assign_edge_trans_members(self.previous_node_tag[-1], self.assigned_node_tag[-1],
                                                             self.global_edge_count)
                            self.edge_node_recorder.setdefault(self.previous_node_tag[-1], self.global_edge_count)
                            self.edge_node_recorder.setdefault(self.assigned_node_tag[-1], self.global_edge_count)
                        elif 90 + self.skew_2 + self.zeta < 90:
                            self.__assign_edge_trans_members(self.previous_node_tag[0], self.assigned_node_tag[0],
                                                             self.global_edge_count)
                            self.edge_node_recorder.setdefault(self.previous_node_tag[0], self.global_edge_count)
                            self.edge_node_recorder.setdefault(self.assigned_node_tag[0], self.global_edge_count)
                    # update recorder for previous node tag step
                    self.previous_node_tag = self.assigned_node_tag
                # update and reset recorders for next column of sweep nodes
                self.global_x_grid_count += 1
                if len(self.assigned_node_tag) == len(self.noz):
                    self.end_connecting_region_nodes = self.assigned_node_tag
                self.ortho_previous_node_column = self.assigned_node_tag
                self.assigned_node_tag = []
            self.global_edge_count += 1
            print("Edge mesh @ end span completed")
        # --------------------------------------------------------------------------------------------
        self.assigned_node_tag = []  # reset
        # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
        # remaining distance mesh with uniform spacing
        # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
        x_first = self.first_connecting_region_nodes[0]
        x_second = self.end_connecting_region_nodes[0]
        # loop each point in self.nox
        cor_fir = self.node_spec[x_first]['coordinate']
        cor_sec = self.node_spec[x_second]['coordinate']
        # get x coordinate for uniform region
        self.uniform_region_x = np.linspace(cor_fir[0], cor_sec[0], self.num_trans_beam)

        for z_count, x in enumerate(self.uniform_region_x[1:-1]):
            # get slope, m at current point x
            # z = line_func(m=self.m, c=self.c, x=x)
            z = self.sweep_path.get_line_function(x)
            # z = line_func(self.sweep_path.m, self.sweep_path.c, x)
            current_sweep_nodes = self.__rotate_sweep_nodes(self.zeta / 180 * np.pi)  # rotating sweep nodes @ origin
            # if angle less than threshold, assign nodes of edge member as it is
            for (z_count_int, nodes) in enumerate(current_sweep_nodes):
                x_inc = x
                z_inc = z
                node_coordinate = [nodes[0] + x_inc, nodes[1], nodes[2] + z_inc]
                self.node_spec.setdefault(self.node_counter, {'tag': self.node_counter, 'coordinate': node_coordinate,
                                                              'x_group': self.global_x_grid_count,
                                                              'z_group': z_count_int})

                self.assigned_node_tag.append(self.node_counter)
                self.node_counter += 1
                # if loop assigned more than two nodes, link nodes as a transverse member
                if z_count_int > 0:
                    # run sub procedure to assign
                    self.__assign_transverse_members(pre_node=self.assigned_node_tag[z_count_int - 1],
                                                     cur_node=self.assigned_node_tag[z_count_int])
            if z_count == 0:
                self.previous_node_tag = self.first_connecting_region_nodes
            elif z_count > 0 and z_count != len(self.uniform_region_x[1:-1]) - 1:
                pass
            for pre_node in self.previous_node_tag:
                for cur_node in self.assigned_node_tag:
                    cur_z_group = self.node_spec[cur_node]['z_group']
                    prev_z_group = self.node_spec[pre_node]['z_group']
                    if cur_z_group == prev_z_group:
                        self.__assign_longitudinal_members(pre_node=pre_node, cur_node=cur_node,
                                                           cur_z_group=cur_z_group)
                        break  # break assign long ele loop (cur node)
            # update and reset recorders for next column of sweep nodes
            self.global_x_grid_count += 1
            # update previous node tag recorder
            if z_count != len(self.uniform_region_x[1:-1]) - 1:
                self.previous_node_tag = self.assigned_node_tag
                self.assigned_node_tag = []
            else:
                self.previous_node_tag = self.assigned_node_tag
                self.assigned_node_tag = self.end_connecting_region_nodes

        # Extra step to connect uniform region with nodes along end span edge region
        for pre_node in self.previous_node_tag:
            for cur_node in self.assigned_node_tag:
                cur_z_group = self.node_spec[cur_node]['z_group']
                prev_z_group = self.node_spec[pre_node]['z_group']
                if cur_z_group == prev_z_group:
                    self.__assign_longitudinal_members(pre_node=pre_node, cur_node=cur_node,
                                                       cur_z_group=cur_z_group)
                    break
        print("orthogonal meshing complete")

    # ------------------------------------------------------------------------------------------
    # ------------------------------------------------------------------------------------------
    def __assign_transverse_members(self, pre_node, cur_node):
        tag = self.__get_geo_transform_tag([pre_node, cur_node])
        self.trans_ele.append([self.element_counter, pre_node, cur_node, self.global_x_grid_count, tag])
        self.element_counter += 1

    def __assign_longitudinal_members(self, pre_node, cur_node, cur_z_group):
        tag = self.__get_geo_transform_tag([pre_node, cur_node])
        self.long_ele.append([self.element_counter, pre_node, cur_node, cur_z_group, tag])
        self.element_counter += 1

    def __assign_edge_trans_members(self, previous_node_tag, assigned_node_tag, edge_counter):
        tag = self.__get_geo_transform_tag([previous_node_tag, assigned_node_tag])
        self.edge_span_ele.append([self.element_counter, previous_node_tag, assigned_node_tag
                                      , edge_counter, tag])
        self.element_counter += 1

    # ------------------------------------------------------------------------------------------
    def __identify_member_groups(self):
        """
        Abstracted method handled by either orthogonal_mesh() or skew_mesh() function
        to identify member groups based on node spacings in orthogonal directions.

        :return: Set variable `group_ele_dict` according to
        """

        # dict common element group to z group
        self.common_z_group_element = dict()
        self.common_z_group_element[0] = [0, len(self.noz) - 1]  # edge beams top and bottom edge
        self.common_z_group_element[1] = [1]  # exterior
        self.common_z_group_element[2] = list(range(2, len(self.noz) - 2))  # interior
        self.common_z_group_element[3] = [len(self.noz) - 2]  # exterior 2

        # dict node tag to width in z direction , and neighbouring node
        self.node_width_z_dict = dict()
        self.node_connect_z_dict = dict()
        for ele in self.long_ele:
            d1 = []  # d for distance
            d2 = []
            p1 = []
            p2 = []
            n1 = [trans_ele for trans_ele in self.trans_ele if trans_ele[1] == ele[1] or trans_ele[2] == ele[1]]
            n2 = [trans_ele for trans_ele in self.trans_ele if trans_ele[1] == ele[2] or trans_ele[2] == ele[2]]
            for item in n1:
                d1.append([np.abs(a - b) for (a, b) in
                           zip(self.node_spec[item[1]]['coordinate'], self.node_spec[item[2]]['coordinate'])])
                if item[1] != ele[1] and item[1] != ele[2]:
                    p1.append(item[1])
                if item[2] != ele[1] and item[2] != ele[2]:
                    p1.append(item[2])

            for item in n2:
                d2.append([np.abs(a - b) for (a, b) in
                           zip(self.node_spec[item[1]]['coordinate'], self.node_spec[item[2]]['coordinate'])])
                if item[1] != ele[1] and item[1] != ele[2]:
                    p2.append(item[1])
                if item[2] != ele[1] and item[2] != ele[2]:
                    p2.append(item[2])
            # list, [ele tag, ele width (left and right)]
            self.node_width_z_dict.setdefault(ele[1], d1)
            self.node_width_z_dict.setdefault(ele[2], d2)
            self.node_connect_z_dict.setdefault(ele[1], p1)
            self.node_connect_z_dict.setdefault(ele[2], p2)

        # dict z to long ele
        self.z_group_to_ele = dict()
        for count, node in enumerate(self.noz):
            self.z_group_to_ele[count] = [ele for ele in self.long_ele if ele[3] == count]

        # dict x to trans ele
        self.x_group_to_ele = dict()
        for count in range(0, self.global_x_grid_count):
            self.x_group_to_ele[count] = [ele for ele in self.trans_ele if ele[3] == count]

        # dict node tag to width in x direction
        self.node_width_x_dict = dict()
        self.node_connect_x_dict = dict()
        for ele in self.trans_ele:
            d1 = []
            d2 = []
            p1 = []
            p2 = []
            n1 = [long_ele for long_ele in self.long_ele if long_ele[1] == ele[1] or long_ele[2] == ele[1]]
            n2 = [long_ele for long_ele in self.long_ele if long_ele[1] == ele[2] or long_ele[2] == ele[2]]
            for item in n1:
                d1.append([np.abs(a - b) for (a, b) in
                           zip(self.node_spec[item[1]]['coordinate'], self.node_spec[item[2]]['coordinate'])])
                if item[1] != ele[1] and item[1] != ele[2]:
                    p1.append(item[1])
                if item[2] != ele[1] and item[2] != ele[2]:
                    p1.append(item[2])
            for item in n2:
                d2.append([np.abs(a - b) for (a, b) in
                           zip(self.node_spec[item[1]]['coordinate'], self.node_spec[item[2]]['coordinate'])])
                if item[1] != ele[1] and item[1] != ele[2]:
                    p2.append(item[1])
                if item[2] != ele[1] and item[2] != ele[2]:
                    p2.append(item[2])
            # list, [ele tag, ele width (left and right)]
            self.node_width_x_dict.setdefault(ele[1], d1)
            self.node_width_x_dict.setdefault(ele[2], d2)
            self.node_connect_x_dict.setdefault(ele[1], p1)
            self.node_connect_x_dict.setdefault(ele[2], p2)

        for ele in self.edge_span_ele:
            d1 = []
            d2 = []
            p1 = []
            p2 = []
            n1 = [long_ele for long_ele in self.long_ele if long_ele[1] == ele[1] or long_ele[2] == ele[1]]
            n2 = [long_ele for long_ele in self.long_ele if long_ele[1] == ele[2] or long_ele[2] == ele[2]]
            for item in n1:
                d1.append([np.abs(a - b) for (a, b) in
                           zip(self.node_spec[item[1]]['coordinate'], self.node_spec[item[2]]['coordinate'])])
                if item[1] != ele[1] and item[1] != ele[2]:
                    p1.append(item[1])
                if item[2] != ele[1] and item[2] != ele[2]:
                    p1.append(item[2])
            for item in n2:
                d2.append([np.abs(a - b) for (a, b) in
                           zip(self.node_spec[item[1]]['coordinate'], self.node_spec[item[2]]['coordinate'])])
                if item[1] != ele[1] and item[1] != ele[2]:
                    p2.append(item[1])
                if item[2] != ele[1] and item[2] != ele[2]:
                    p2.append(item[2])
            # list, [ele tag, ele width (left and right)]
            self.node_width_x_dict.setdefault(ele[1], d1)
            self.node_width_x_dict.setdefault(ele[2], d2)
            self.node_connect_x_dict.setdefault(ele[1], p1)
            self.node_connect_x_dict.setdefault(ele[2], p2)
        # create self.grid_number_dict, dict key = grid number, val = long and trans ele in grid
        self.grid_number_dict = dict()
        counter = 0
        for node_tag in self.node_spec.keys():
            # get the surrounding nodes
            x_vicinity_nodes = self.node_connect_x_dict.get(node_tag, [])
            z_vicinity_nodes = self.node_connect_z_dict.get(node_tag, [])
            for x_node in x_vicinity_nodes:
                xg = self.node_spec[x_node]['x_group']
                for z_node in z_vicinity_nodes:
                    zg = self.node_spec[z_node]['z_group']
                    # find the 3rd bounding node
                    n3 = [n['tag'] for n in self.node_spec.values() if n['x_group'] == xg and n['z_group'] == zg]
                    if n3:
                        n3 = n3[0]
                        if not any([node_tag in d and x_node in d and z_node in d and n3 in d for d in
                                    self.grid_number_dict.values()]):
                            self.grid_number_dict.setdefault(counter, [node_tag, x_node, n3, z_node])
                            counter += 1
                    else:  # list is empty
                        if not any([node_tag in d and x_node in d and z_node in d for d in
                                    self.grid_number_dict.values()]):
                            self.grid_number_dict.setdefault(counter, [node_tag, x_node, n3, z_node])
                            counter += 1

        # dict of grid number return vicinity grid number in a subdict {'x-1': 'x+1', 'z-1' , 'z+1'}
        self.grid_vicinity_dict = dict()
        for k, grid in self.grid_number_dict.items():
            current_x_group = []
            current_z_group = []
            current_x = []
            current_z = []

            grid_number_record = []
            if [] in grid:
                grid.remove([])
            for node in grid:
                grid_number_record += [i for i, x in enumerate([node in n for n in self.grid_number_dict.values()]) if
                                       x]
                current_x_group.append(self.node_spec[node]['x_group'])
                current_z_group.append(self.node_spec[node]['z_group'])
                current_x.append(self.node_spec[node]['coordinate'][0])
                current_z.append(self.node_spec[node]['coordinate'][2])
            current_x_group = list(np.unique(current_x_group))
            current_z_group = list(np.unique(current_z_group))
            current_x = list(np.unique(current_x))
            current_z = list(np.unique(current_z))
            grid_number_record = np.unique(grid_number_record)
            # loop to characterize the grid for current
            subdict = {}
            for neighbour in grid_number_record:
                if neighbour == k:  # identical , current grid
                    continue
                x_group = []  # initialize variables
                x_coor = []
                z_group = []
                z_coor = []
                # loop each node in the vicintiy grids
                for nodes in self.grid_number_dict[neighbour]:
                    if not nodes:
                        continue
                    x_group.append(self.node_spec[nodes]['x_group'])
                    z_group.append(self.node_spec[nodes]['z_group'])
                    x_coor.append(self.node_spec[nodes]['coordinate'][0])
                    z_coor.append(self.node_spec[nodes]['coordinate'][2])
                x_group = list(np.unique(x_group))
                z_group = list(np.unique(z_group))
                x_coor = list(np.unique(x_coor))
                z_coor = list(np.unique(z_coor))
                # if x groups are identical, neighbour grid is either top or bottom of the element
                if all(a in current_x_group for a in x_group):
                    # compare z max
                    if max(z_coor) > max(current_z):
                        subdict['top'] = neighbour
                    else:
                        subdict['bottom'] = neighbour
                # if x groups are identical, neighbour grid is either left or right of the element
                if all(a in current_z_group for a in z_group):
                    if max(x_coor) > max(current_x):
                        subdict['right'] = neighbour
                    else:
                        subdict['left'] = neighbour
            self.grid_vicinity_dict.setdefault(k, subdict)

    def __get_geo_transform_tag(self, ele_nodes):
        # function called for each element, assign
        node_i = self.node_spec[ele_nodes[0]]['coordinate']
        node_j = self.node_spec[ele_nodes[1]]['coordinate']
        vxz = self.__get_vector_xz(node_i, node_j)
        vxz = [np.round(num, decimals=self.decimal_lim) for num in vxz]
        tag_value = self.transform_dict.setdefault(repr(vxz), self.transform_counter + 1)
        if tag_value > self.transform_counter:
            self.transform_counter = tag_value
        return tag_value

    def __check_skew(self, zeta):
        # zeta in DEGREES
        # if mesh type is beyond default allowance threshold of 11 degree and 30 degree, return exception
        if np.abs(self.skew_1 - zeta) <= self.skew_threshold[0] and self.orthogonal:
            # return error
            raise Exception("Skew angle too small for orthogonal")
            self.orthogonal = False
        elif np.abs(self.skew_1 - zeta) >= self.skew_threshold[1] and not self.orthogonal:
            self.orthogonal = True
            raise Exception("Skew angle too large for skewed")
            # raise Exception('Oblique mesh not allowed for angle greater than {}'.format(self.skew_threshold[1]))

    # ------------------------------------------------------------------------------------------
    @staticmethod
    def __get_vector_xz(node_i, node_j):
        """
        Encapsulated function to identify a vector parallel to the plane of local x and z axis of the element. The
        vector is required for geomTransf() command
        - see geomTransf_.

        .. _geomTransf: https://openseespydoc.readthedocs.io/en/latest/src/geomTransf.html

        """
        # Function to calculate vector xz used for geometric transformation of local section properties
        # return: vector parallel to plane xz of member (see geotransform Opensees) for skew members (member tag 5)

        # vector rotate 90 deg clockwise (x,y) -> (y,-x)
        # [breadth width] is a vector parallel to skew
        xi = node_j[0] - node_i[0]
        zi = node_j[2] - node_i[2]
        x = zi
        z = -xi
        # normalize vector
        length = np.sqrt(x ** 2 + z ** 2)
        x1 = x / length

        z1 = z / length
        return [x1, 0, z1]  # here y axis is normal to model plane

    def __rotate_sweep_nodes(self, zeta):
        sweep_nodes_x = [0] * len(self.noz)  # line is orthogonal at the start of sweeping path
        # rotate for inclination at origin
        sweep_nodes_x = [x * np.cos(zeta) - y * np.sin(zeta) for x, y in zip(sweep_nodes_x, self.noz)]
        sweep_nodes_z = [y * np.cos(zeta) + x * np.sin(zeta) for x, y in zip(sweep_nodes_x, self.noz)]

        sweeping_nodes = [[x + self.mesh_origin[0], y + self.mesh_origin[1], z + self.mesh_origin[2]] for x, y, z
                          in
                          zip((sweep_nodes_x), [self.y_elevation] * len(self.noz), sweep_nodes_z)]

        return sweeping_nodes

    def __search_x_point(self, int_point, start_point_y=0, line_function=None):
        start_point_x = int_point[0]
        min_found = False
        max_loop = 1000
        loop_counter = 0
        z0 = None
        inc = self.search_x_inc
        convergence_check = []
        bounds = []
        while not min_found:
            z0 = self.sweep_path.get_line_function(start_point_x)
            z_ub = self.sweep_path.get_line_function(start_point_x + inc)
            z_lb = self.sweep_path.get_line_function(start_point_x - inc)
            d0 = find_min_x_dist([int_point], [[start_point_x, self.y_elevation, z0]]).tolist()

            d_ub = find_min_x_dist([int_point], [[start_point_x + inc, self.y_elevation, z_ub]]).tolist()

            d_lb = find_min_x_dist([int_point], [[start_point_x - inc, self.y_elevation, z_lb]]).tolist()

            if d_lb > d0 and d_ub > d0:
                min_found = True
            elif d_lb < d0 and d_ub > d0:
                start_point_x = start_point_x - inc
            elif d_lb > d0 and d_ub < d0:
                start_point_x = start_point_x + inc

            loop_counter += 1
            if loop_counter > max_loop:
                break

        return start_point_x, z0


class EdgeConstructionLine:
    """
    edge node class
    """

    def __init__(self, edge_ref_point, width_z, edge_width_z, edge_angle, num_long_beam, model_plane_y,
                 feature="start"):
        # set variables
        self.edge_ref_point = edge_ref_point
        self.width_z = width_z
        self.edge_width_z = edge_width_z
        self.num_long_beam = num_long_beam
        self.edge_angle = edge_angle
        self.feature = feature
        # calculations
        last_girder = (self.width_z - self.edge_width_z)  # coord of last girder
        nox_girder = np.linspace(start=self.edge_width_z, stop=last_girder, num=self.num_long_beam - 2)
        # array containing z coordinate of edge construction line
        self.noz = np.hstack((np.hstack((0, nox_girder)), self.width_z))

        if self.edge_angle <= 0:
            edge_node_x = [-(z * np.tan(self.edge_angle / 180 * np.pi)) for z in self.noz]
            self.node_list = [[x + self.edge_ref_point[0], y + self.edge_ref_point[1], z + self.edge_ref_point[2]] for
                              x, y, z in
                              zip(edge_node_x, [model_plane_y] * len(self.noz), self.noz)]
        else:
            edge_node_x = [-(z * np.tan(self.edge_angle / 180 * np.pi)) for z in self.noz]
            self.node_list = [[x + self.edge_ref_point[0], y + self.edge_ref_point[1], z + self.edge_ref_point[2]] for
                              x, y, z in zip(edge_node_x, [model_plane_y] * len(self.noz), self.noz)]

        self.z_group = list(range(0, len(self.noz)))

        self.slope = -1 / np.tan(self.edge_angle / 180 * np.pi) if self.edge_angle != 0 else None
        self.c = get_y_intcp(self.slope, self.edge_ref_point[0],
                             self.edge_ref_point[2]) if self.edge_angle != 0 else None

    def get_node_group_z(self, coordinate):
        # return list of zgroup
        group = self.node_list.index(coordinate)
        return group


class SweepPath:
    def __init__(self, pt1: Point, pt2: Point, pt3: Point = None):
        """

        :param pt1: Namedtuple Point of first coordinate
        :param pt2: Namedtuple Point of second coordinate
        :param pt3: Namedtuple Point of third coordinate
        """
        self.pt1 = pt1
        self.pt2 = pt2
        self.pt3 = pt3
        self.decimal_lim = 4
        self.curve_path = False
        # return variables
        self.zeta = None
        self.m = None
        self.c = 0  # Default:0 , sweep path intersects origin

    def get_sweep_line_properties(self):
        if self.pt3 is not None:
            try:
                self.d = findCircle(x1=0, y1=0, x2=self.pt2.x, y2=self.pt2.z, x3=self.pt3.x, y3=self.pt3.z)
                self.curve_path = True
            except ZeroDivisionError:
                return Exception("Zero div error. Point 3 not valid to construct curve line")
            # procedure
            # get tangent at origin
            self.zeta = 0
        else:
            # construct straight line sweep path instead
            self.d = None
            # procedure to identify straight line segment pinpointing length of grillage
            points = [(self.pt1.x, self.pt1.z), (self.pt2.x, self.pt2.z)]
            x_coords, y_coords = zip(*points)
            A = np.vstack([x_coords, np.ones(len(x_coords))]).T
            m, c = np.linalg.lstsq(A, y_coords, rcond=None)[0]
            self.m = round(m, self.decimal_lim)
            # self.c = 0  # default 0  to avoid arithmetic error
            zeta = np.arctan(m)  # initial angle of inclination of sweep line about mesh origin
            self.zeta = zeta / np.pi * 180  # rad to degrees

        return self.zeta, self.m, self.c

    def get_line_function(self, x):
        if not self.curve_path:
            # straight line
            return line_func(self.m, self.c, x)
        else:
            pass
