import numpy as np
import math
import openseespy.opensees as ops
from datetime import datetime
from collections import defaultdict
from static import *
from Load import *
from Material import *
from member_sections import *
from Mesh import *


class OpsGrillage:
    """
    Main class of Openseespy grillage model wrapper. Outputs an executable py file which generates the prescribed
    Opensees grillage model based on user input.

    The class provides an interface for the user to specify the geometry of the grillage model. A keyword argument
    allows for users to select between skew/oblique or orthogonal mesh. Methods in this class allows users to input
    properties for various elements in the grillage model.
    """

    def __init__(self, bridge_name, long_dim, width, skew, num_long_grid,
                 num_trans_grid, edge_beam_dist, mesh_type="Ortho", op_instance=True, model="3D", **kwargs):
        """

        :param bridge_name: Name of bridge model and output .py file
        :type bridge_name: str
        :param long_dim: Length of the model in the longitudinal direction (default: x axis)
        :type long_dim: int or float
        :param width: Width of the model in the transverse direction (default: z axis)
        :type width: int or float
        :param skew: Skew angle of model
        :type skew: int or float
        :param num_long_grid: Number of node points in the longitudinal direction
        :type num_long_grid: int
        :param num_trans_grid: Number of node points in the transverse direction
        :type num_trans_grid: int
        :param edge_beam_dist: Distance of edge beam node lines to exterior main beam node lines
        :type edge_beam_dist: int or float
        :param mesh_type: Type of mesh
        :type mesh_type: string

        """

        # model information
        self.mesh_type = mesh_type
        self.model_name = bridge_name
        self.op_instance_flag = op_instance

        # global dimensions of grillage
        self.long_dim = long_dim  # span , also c/c between support bearings
        self.width = width  # length of the bearing support - if skew  = 0 , this corresponds to width of bridge
        self.skew = skew  # angle in degrees

        # Variables for grillage grillage
        self.num_long_gird = num_long_grid  # number of longitudinal beams
        self.num_trans_grid = num_trans_grid  # number of grids for transverse members
        self.edge_width = edge_beam_dist  # width of cantilever edge beam
        self.regA = []
        self.regB = []
        self.edge_beam_nodes = []
        # instantiate matrices for geometric dependent properties
        self.trans_dim = None  # to be calculated automatically based on skew
        self.breadth = None  # to be calculated automatically based on skew
        self.spclonggirder = None  # to be automated
        self.spctransslab = None  # to be automated

        # initialize lists
        self.node_map = []  # array like to be populated
        self.nox = []  # line mesh in x direction
        self.noz = []  # line mesh in z direction
        # initiate list of various elements of grillage model, each entry of list is a sublist [node_i, node_j, eletag]
        self.long_mem = []  # longitudinal members
        self.trans_mem = []  # transverse members
        self.support_nodes = []  # list of nodes at support regions
        self.vxz_skew = []  # vector xz of skew elements - for section transformation
        self.global_mat_object = []  # material matrix
        self.noz_trib_width = []
        self.nox_trib_width = []
        # initialize tags of grillage elements - default tags are for standard elements of grillage
        # Section placeholders
        self.section_arg = None
        self.section_tag = None
        self.section_type = None
        self.section_group_noz = []  # list of tag representing ele groups of long mem
        self.section_group_nox = []  # list of tag representing ele groups of trans mem
        self.spacing_diff_noz = []
        self.spacing_diff_nox = []
        # dict
        self.group_ele_dict = None  # dictionary of ele groups e.g. [ "name of group": tag ]
        self.global_element_list = None  # list of all elements in grillage
        self.ele_group_assigned_list = []  # list recording assigned ele groups in grillage model
        self.section_dict = {}  # dictionary of section tags
        self.material_dict = {}  # dictionary of material tags
        self.spacing_val_noz = []  # dict of group as keywords, val = spacing
        self.spacing_val_nox = []  # dict of group as keywords, val = spacing
        # collect mesh groups
        self.mesh_group = []
        if self.mesh_type == "Ortho":
            self.ortho_mesh = True
        else:
            self.ortho_mesh = False
        # rules for grillage automation - default values are in place, use keyword during class instantiation
        self.grillage_rules_dict = dict()
        self.grillage_rules_dict['min_long_spacing'] = kwargs.get('min_long_spacing', 1)
        self.grillage_rules_dict['max_long_spacing'] = kwargs.get('max_long_spacing', 1)
        self.grillage_rules_dict['min_trans_spacing'] = kwargs.get('min_trans_spacing', 1)
        self.grillage_rules_dict['max_trans_spacing'] = kwargs.get('max_trans_spacing', 1)
        self.grillage_rules_dict['aspect_ratio'] = kwargs.get('aspect_ratio', 1)

        self.y_elevation = 0  # default elevation of grillage wrt OPmodel coordinate system
        self.min_grid_ortho = 3  # for orthogonal mesh (skew>skew_threshold) region of orthogonal area default 3

        if model == "2D":
            self.__ndm = 2  # num model dimension - default 3
            self.__ndf = 3  # num degree of freedom - default 6
        else:
            self.__ndm = 3  # num model dimension - default 3
            self.__ndf = 6  # num degree of freedom - default 6

        # default vector for support (for 2D grillage in x - z plane)
        self.fix_val_pin = [1, 1, 1, 0, 0, 0]  # pinned
        self.fix_val_roller_x = [0, 1, 1, 0, 0, 0]  # roller
        # special rules for grillage - alternative to Properties of grillage definition - use for special dimensions
        self.nox_special = None  # array specifying custom coordinate of longitudinal nodes
        self.noz_special = None  # array specifying custom coordinate of transverse nodes
        self.skew_threshold = [10, 30]  # threshold for grillage to allow option of mesh choices
        self.deci_tol = 4  # tol of decimal places

        # dict for load cases and load types
        self.load_case_dict = defaultdict(lambda: 1)
        self.nodal_load_dict = defaultdict(lambda: 1)
        self.ele_load_dict = defaultdict(lambda: 1)

        # counters to keep track of objects
        self.load_case_counter = 1
        self.load_combination_counter = 1

        # Initiate py file output
        self.filename = "{}_op.py".format(self.model_name)
        with open(self.filename, 'w') as file_handle:
            # create py file or overwrite existing
            # writing headers and description at top of file
            file_handle.write("# Grillage generator wizard\n# Model name: {}\n".format(self.model_name))
            # time
            now = datetime.now()
            dt_string = now.strftime("%d/%m/%Y %H:%M:%S")
            file_handle.write("# Constructed on:{}\n".format(dt_string))
            # write imports
            file_handle.write("import numpy as np\nimport math\nimport openseespy.opensees as ops"
                              "\nimport openseespy.postprocessing.Get_Rendering as opsplt\n")

        # check skew threshold
        #TODO turn on later
        #self.__check_skew()

        # calculate edge length of grillage
        self.trans_dim = self.width / math.cos(self.skew / 180 * math.pi)
        # 1 create Opensees model space
        self.__write_op_model()
        self.Mesh_obj = None
        self.__run_mesh_generation()

    def __run_mesh_generation(self):
        """
        Abstracted procedure to create nodes of grillage model. This procedure also handles sub-abstracted procedures
        involved in writing Opensees command: model(), node(), and fix() commands to output py file.
        :return: Output py file with model(), node() and fix() commands
        """

        if self.ortho_mesh:
            # perform orthogonal meshing
            self.__orthogonal_mesh()
        else:  # perform skew mesh
            self.__skew_mesh()
        v = self.__get_vector_xz()

        self.Mesh_obj = Mesh(self.long_dim, self.width, self.trans_dim, self.edge_width, self.num_trans_grid,
                             self.num_long_gird,
                             self.skew, orthogonal=self.ortho_mesh)
        print("new mesh")

        # 2 generate command lines in output py file
        self.__write_op_node(self.Mesh_obj)  # write node() commands
        self.__write_geom_transf(self.Mesh_obj)  # x dir members
        # 3 identify boundary of mesh
        # TODO hereafter modify to read properties from Mesh.obj
        self.get_edge_beam_nodes()  # get edge beam nodes
        self.get_trans_edge_nodes()  # get support nodes
        self.__write_op_fix()  # write fix() command for support nodes

    def set_boundary_condition(self, restraint_nodes=[], restraint_vector=[]):
        """
        User function to define support boundary conditions in addition to the model edges automatically detected
        by create_nodes() procedure.

        :param restraint_nodes: list of node tags to be restrained
        :type restraint_nodes: list
        :param restraint_vector: list representing node restraint for Nx Ny Nz, Mx My Mz respectively.
                                    represented by 1 (fixed), and 0 (free)
        :type restraint_vector: list
        :return: Append node fixity to the support_nodes class variable
        """
        for nodes in restraint_nodes:
            self.support_nodes.append([nodes, restraint_vector])

    # abstraction to write ops commands to output py file
    def __write_geom_transf(self, mesh_obj, transform_type="Linear"):
        """
        Abstracted procedure to write ops.geomTransf() to output py file.
        :param trans_tag: tag of transformation - set according to default 1, 2 and 3
        :param vector_xz: vector parallel to plane xz of the element. Automatically calculated by get_vector_xz()
        :param transform_type: transformation type
        :type transform_type: str

        :return: Writes ops.geomTransf() line to output py file
        """

        # write geoTransf() command
        # ops.geomTransf(transform_type, trans_tag, *vector_xz)
        # with open(self.filename, 'a') as file_handle:
        #     file_handle.write("# create transformation {}\n".format(trans_tag))
        #     file_handle.write("ops.geomTransf(\"{type}\", {tag}, *{vxz})\n".format(
        #         type=transform_type, tag=trans_tag, vxz=vector_xz))

        for k,v in mesh_obj.transform_dict.items():
            ops.geomTransf(transform_type, v, *eval(k))
            with open(self.filename, 'a') as file_handle:
                file_handle.write("# create transformation {}\n".format(v))
                file_handle.write("ops.geomTransf(\"{type}\", {tag}, *{vxz})\n".format(
                    type=transform_type, tag=v, vxz=eval(k)))

    def __write_op_model(self):
        """
        Sub-abstracted procedure handled by create_nodes() function. This method creates the model() command
        in the output py file.

        :return: Output py file with wipe() and model() commands

        Note: For 3-D model, the default model dimension and node degree-of-freedoms are 3 and 6 respectively.
        This method automatically sets the aforementioned parameters to 2 and 4 respectively, for a 2-D problem.
        """
        # write model() command
        ops.model('basic', '-ndm', self.__ndm, '-ndf', self.__ndf)
        with open(self.filename, 'a') as file_handle:
            file_handle.write("ops.wipe()\n")
            file_handle.write(
                "ops.model('basic', '-ndm', {ndm}, '-ndf', {ndf})\n".format(ndm=self.__ndm, ndf=self.__ndf))

    def __write_op_node(self,mesh_obj):
        """
        Sub-abstracted procedure handled by create_nodes() function. This method create node() command for each node
        point generated during meshing procedures.

        :return: Output py file populated with node() commands to generated the prescribed grillage model.
        """
        # write node() command
        with open(self.filename, 'a') as file_handle:
            file_handle.write("# Node generation procedure\n")
        # for node_point in self.node_map:
        #     ops.node(node_point[0], node_point[1], node_point[2], node_point[3])
        #     with open(self.filename, 'a') as file_handle:
        #         file_handle.write("ops.node({tag}, {x:.4f}, {y:.4f}, {z:.4f})\n".format(tag=node_point[0],
        #                                                                                 x=node_point[1],
        #                                                                                 y=node_point[2],
        #                                                                                 z=node_point[3]))
        for k,nested_v, in mesh_obj.node_spec.items():
            coordinate = nested_v['coordinate']
            ops.node(nested_v['tag'], coordinate[0], coordinate[1], coordinate[2])
            with open(self.filename, 'a') as file_handle:
                file_handle.write("ops.node({tag}, {x:.4f}, {y:.4f}, {z:.4f})\n".format(tag=nested_v['tag'],
                                                                                        x=coordinate[0],
                                                                                        y=coordinate[1],
                                                                                        z=coordinate[2]))


    def __write_op_fix(self):
        """
        Abstracted procedure handed by create_nodes() function. This method writes the fix() command for
        boundary condition defintion in the grillage model.

        :return: Output py file populated with fix() command for boundary condition definition.
        """
        with open(self.filename, 'a') as file_handle:
            file_handle.write("# Boundary condition implementation\n")
        for boundary in self.support_nodes:
            # ops.fix(boundary[0], *boundary[1])
            with open(self.filename, 'a') as file_handle:
                file_handle.write("ops.fix({}, *{})\n".format(boundary[0], boundary[1]))

    def __write_uniaxial_material(self, member=None, material=None):
        """
        Sub-abstracted procedure to write uniaxialMaterial command for the material properties of the grillage model.

        :return: Output py file with uniaxialMaterial() command
        """
        # function to generate uniaxialMaterial() command in output py file
        # ops.uniaxialMaterial(self.mat_type_op, 1, *self.mat_matrix)

        if member is None and material is None:
            raise Exception("Uniaxial material has no input GrillageMember or Material Object")
        if member is None:
            material_obj = material  # str of section type - Openseespy convention

        elif material is None:
            material_obj = member.material  # str of section type - Openseespy convention
        material_type = material_obj.mat_type
        op_mat_arg = material_obj.mat_vec

        # - write unique material tag and input argument as keyword of dict
        material_str = [material_type, op_mat_arg]  # repr both variables as a list for keyword definition
        # if section is specified, get the materialtagcounter for material() assignment
        if not bool(self.material_dict):
            lastmaterialtag = 0  # if dict empty, start counter at 1
        else:  # set materialtagcounter as the latest defined element - i.e. max of section_dict
            lastmaterialtag = self.material_dict[list(self.material_dict)[-1]]

        # if section has been assigned
        material_tag = self.material_dict.setdefault(repr(material_str), lastmaterialtag + 1)
        if material_tag != lastmaterialtag:
            with open(self.filename, 'a') as file_handle:
                file_handle.write("# Material definition \n")
                file_handle.write("ops.uniaxialMaterial(\"{type}\", {tag}, *{vec})\n".format(
                    type=material_type, tag=material_tag, vec=op_mat_arg))
        else:
            print("Material {} with tag {} has been previously defined"
                  .format(material_type, material_tag))
            return material_tag

    def __identify_member_groups(self):
        """
        Abstracted method handled by either orthogonal_mesh() or skew_mesh() function
        to identify member groups based on node spacings in orthogonal directions.

        :return: Set variable `group_ele_dict` according to
        """
        # identify element groups in grillage based on line mesh vectors self.nox and self.noz

        # get the grouping properties of nox
        # grouping number, dictionary of unique groups, dict of spacing values for given group as key, list of trib
        # area of nodes
        self.section_group_noz, self.spacing_diff_noz, self.spacing_val_noz, self.noz_trib_width \
            = characterize_node_diff(self.noz, self.deci_tol)
        self.section_group_nox, self.spacing_diff_nox, self.spacing_val_nox, self.nox_trib_width \
            = characterize_node_diff(self.nox, self.deci_tol)
        # update self.section_group_nox counter to continue after self.section_group_noz
        self.section_group_nox = [x + max(self.section_group_noz) for x in self.section_group_nox]

        if self.ortho_mesh:
            # update self.section_group_nox first element to match counting for element group of Region B
            self.section_group_nox[0] = self.section_group_nox[len(self.regA) - 1]
        else:  # else skew mesh do nothing
            pass
        # set groups dictionary
        if self.ortho_mesh:  # if ortho mesh
            if max(self.section_group_noz) <= 4:  # if true , standard sections set for longitudinal members
                self.group_ele_dict = {"edge_beam": 1, "exterior_main_beam_1": 2, "interior_main_beam": 3,
                                       "exterior_main_beam_2": 4, "edge_slab": 5, "transverse_slab": 6}
            else:  # groups
                self.group_ele_dict = {"edge_beam": 1, "exterior_main_beam_1": 2, "interior_main_beam": 3,
                                       "exterior_main_beam_2": 4, "edge_slab": 5, "transverse_slab": 6}
            # TODO : add rules here
        else:  # skew mesh, run generate respective group dictionary
            if max(self.section_group_noz) <= 4:
                # dictionary applies to longitudinal members only
                self.group_ele_dict = {"edge_beam": 1, "exterior_main_beam_1": 2, "interior_main_beam": 3,
                                       "exterior_main_beam_2": 4, "edge_slab": 5, "transverse_slab": 6}
            else:  # section grouping greater than 6

                # set variable up to 4 group (longitudinal)
                self.group_ele_dict = {"edge_beam": 1, "exterior_main_beam_1": 2, "interior_main_beam": 3,
                                       "exterior_main_beam_2": 4}
                # for transverse (group 5 and above) assign based on custom number

            # orthogonal mesh rules
        # print groups to terminal
        print("Total groups of elements in longitudinal : {}".format(max(self.section_group_noz)))
        print("Total groups of elements in transverse : {}".format(max(self.section_group_nox)))

    def __write_section(self, op_section_obj):
        """
        Abstracted procedure handled by set_member() function to write section() command for the elements. This method
        is ran only when GrillageMember object requires section() definition following convention of Openseespy.

        """
        # extract section variables from Section class
        section_type = op_section_obj.op_section_type  # str of section type - Openseespy convention
        # section argument
        section_arg = op_section_obj.get_asterisk_arguments()  # list of argument for section - Openseespy convention
        section_str = [section_type, section_arg]  # repr both variables as a list for keyword definition
        # if section is specified, get the sectiontagcounter for section assignment
        if not bool(self.section_dict):
            lastsectioncounter = 0  # if dict empty, start counter at 0
        else:  # dict not empty, get default value as latest defined tag
            lastsectioncounter = self.section_dict[list(self.section_dict)[-1]]
        # if section has been assigned
        sectiontagcounter = self.section_dict.setdefault(repr(section_str), lastsectioncounter + 1)
        if sectiontagcounter != lastsectioncounter:
            with open(self.filename, 'a') as file_handle:
                file_handle.write("# Create section: \n")
                file_handle.write(
                    "ops.section(\"{}\", {}, *{})\n".format(section_type, sectiontagcounter, section_arg))
            # print to terminal
            print("Section {}, of tag {} created".format(section_type, sectiontagcounter))
        else:
            print("Section {} with tag {} has been previously defined"
                  .format(section_type, sectiontagcounter))
        return sectiontagcounter

    def __get_vector_xz(self):
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
        x = self.width
        y = -(-self.breadth)
        # normalize vector
        length = math.sqrt(x ** 2 + y ** 2)
        vec = [x / length, y / length]
        return vec

    def __get_region_b(self, reg_a_end, noz):
        """
        Abstracted procedure to define the varying spacing nodes in orthogonal mesh (near support edges). This
        method is called within orthogonal_mesh() or skew_mesh.

        :return: list of nodes within the skew edge regions

        """
        # Function to calculate the node coordinate for skew region B
        # -> triangular breadth along the longitudinal direction
        # :param step: list containing transverse nodes (along z dir)
        # :param reg_a_end: last node from regA (quadrilateral region)
        # :return: node coordinate for skew triangular area (region B1 or B2)

        regB = [reg_a_end]  # initiate array regB
        for node in range(2, len(noz)):  # minus 2 to ignore first and last element of step
            regB.append(self.long_dim - noz[-node] * np.abs(np.tan(self.skew / 180 * math.pi)))
        # after append, add last element - self.long_dim
        regB.append(self.long_dim)
        regB = np.array(regB)
        return regB

    def __check_skew(self):
        """
        Function to set boolean to true if orthogonal mesh option. This function is automatically called during __init__
        Function also checks if skew angle lies in allowable threshold
        - between 10-30 degree (var self.skew_threshold) both types of mesh (skew and orthogonal) are allowed.
        outside this bound, skew rules are strictly: (1) skew for angles less than 10 deg, and
        (2) orthogonal for angles greater than 30 deg.
        """

        # if mesh type is beyond default allowance threshold of 11 degree and 30 degree, return exception
        if np.abs(self.skew) <= self.skew_threshold[0] and self.ortho_mesh:
            # print
            raise Exception('Orthogonal mesh not allowed for angle less than {}'.format(self.skew_threshold[0]))
        elif np.abs(self.skew) >= self.skew_threshold[1] and not self.ortho_mesh:
            raise Exception('Oblique mesh not allowed for angle greater than {}'.format(self.skew_threshold[1]))

    def set_member(self, grillage_member_obj, member=None):
        """
        Function to assign GrillageMember obj to element groups. Function then create ops.element() command for the
        prescribed element.

        :param grillage_member_obj: Member object
        :param member: str of grillage element group to be assigned

        :return: assign member properties to all grillage element within specified group.

        """
        # checks for GrillageMember object
        if isinstance(grillage_member_obj, GrillageMember):
            pass  # proceed with setting members
        else:  # raise exception
            Exception("Input member {} not a GrillageMember class".format(grillage_member_obj))
        # if member is defined with unit width properties
        if grillage_member_obj.section.unit_width:
            # get tributary area of node (node_width) defined as half of spacings left and right of element
            ele_width = self.spacing_val_nox[self.group_ele_dict[member] - max(self.section_group_noz)]
            # calculate properties based on tributary area
            # prop = grillage_member_class.section.get_output_arguments(node_width / 2)
        else:  # set properties as it is
            # prop = grillage_member_class.section.get_output_arguments()
            ele_width = 1
        # if ele group has been assigned.
        if member in self.ele_group_assigned_list:
            raise Exception('Element Group {} has already been assigned'.format(member))
        # TODO add option for overwriting
        # if member group to be set is not defined
        if member is None:
            raise Exception('Str of member group not specified')

        # if section is specified, get the section from GrillageMember class and write to
        if grillage_member_obj.section.section_command_flag:
            # abstracted procedure to write section command
            section_tag = self.__write_section(grillage_member_obj.section)

        # set material of member, if already set (either globally via set_material function or same material for a
        # previous set_member command, function automatically skips the writing of material command
        material_tag = self.__write_uniaxial_material(member=grillage_member_obj)

        # write header of set_member run
        with open(self.filename, 'a') as file_handle:
            file_handle.write("# Element generation for section: {}\n".format(member))

        # if assignment of all transverse members based on per m width properties
        if grillage_member_obj.section.unit_width:
            # loop through the unique members based on spacings of nodes, assign all members (key-tag) in the transverse
            # direction
            for key, ele_width in self.spacing_val_nox.items():
                # loop through each transverse group (spacings)
                for ele in self.global_element_list:
                    if ele[2] == key + max(
                            self.section_group_noz):  # if element match key for transverse memeber loop
                        # get element() command for element
                        ele_str = grillage_member_obj.section.get_element_command_str(ele, ele_width=ele_width)
                        # write element() command to file
                        with open(self.filename, 'a') as file_handle:
                            file_handle.write(ele_str)
                        eval(ele_str)
                # add ele group to assigned list
                self.ele_group_assigned_list.append(key + max(self.section_group_noz))
        else:
            # direct assignment
            for ele in self.global_element_list:
                # ops.element(beam_ele_type, ele[3],
                #            *[ele[0], ele[1]], *op_member_prop_class, trans_tag)  ###
                if ele[2] == self.group_ele_dict[member]:
                    # get element() command for the element
                    ele_str = grillage_member_obj.section.get_element_command_str(ele, ele_width=ele_width)
                    # write element() command to file
                    with open(self.filename, 'a') as file_handle:
                        file_handle.write(ele_str)
                    eval(ele_str)

            # add ele group to assigned list
            self.ele_group_assigned_list.append(self.group_ele_dict[member])

        # print to terminal
        print("Assigned member groups {}".format(repr(self.ele_group_assigned_list)))
        if len(self.ele_group_assigned_list) != max(self.section_group_nox):
            print("Unassigned member groups: {}".format(
                diff(range(1, max(self.section_group_nox) + 1), self.ele_group_assigned_list)))
        else:
            print("All member groups have been assigned")

    def get_trans_edge_nodes(self):
        """
        Abstracted procedure to automatically identify the support edges of the model/mesh group. Function can be called
        outside of class to return the list of edge nodes
        """
        # function to identify nodes at edges of the model along transverse direction (trans_edge_1 and trans_edge_2)
        # function then assigns pinned support and roller support to nodes in trans_edge_1 and trans_edge_2 respectively
        assign_list = []  # list recording assigned elements to check against double assignment
        for (count, ele) in enumerate(self.trans_mem):
            if self.ortho_mesh:  # if orthogonal mesh
                if ele[2] == 5:  # if its a support node (tag = 5 default for skew)
                    # if not ele[0] in assign_list:  # check if ele is not in the assign list
                    #    assign_list.append(ele[0])
                    #    self.support_nodes.append([ele[0], self.fix_val_pin])

                    # if true, assign ele as support
                    if not ele[1] in assign_list:  # check if ele is not in the assign list
                        assign_list.append(ele[1])
                        self.support_nodes.append([ele[1], self.fix_val_pin])
            else:  # skew mesh
                if ele[2] == 5:  # if its a support node (tag = 5 default for skew)
                    # if not ele[0] in assign_list:  # check if ele is not in the assign list
                    #    assign_list.append(ele[0])
                    #    self.support_nodes.append([ele[0], self.fix_val_pin])

                    # if true, assign ele as support
                    if not ele[1] in assign_list:  # check if ele is not in the assign list
                        assign_list.append(ele[1])
                        self.support_nodes.append([ele[1], self.fix_val_pin])
        # next, remove edge beam nodes, first make a handler for list
        support_node_copy = self.support_nodes
        for (count, sup_node) in enumerate(self.support_nodes):
            # if node is an edge beam node
            if sup_node[0] in self.edge_beam_nodes:
                # remove node
                support_node_copy.pop(count)
        # reassign self.support_node with support_node_copy
        self.support_nodes = support_node_copy
        # if called outside class, return variable to user
        return self.support_nodes

    def get_edge_beam_nodes(self):
        """
        Abstracted procedure to automatically identify nodes correspond to edge beams of the model/mesh group.
        Function can be called outside of class to return the list of edge beam nodes
        """
        for (count, ele) in enumerate(self.global_element_list):
            if ele[2] == 1:
                self.edge_beam_nodes.append(ele[0])
                self.edge_beam_nodes.append(ele[1])

        self.edge_beam_nodes = np.unique(self.edge_beam_nodes)
        return self.edge_beam_nodes

    def get_long_grid_nodes(self):
        """
        Abstracted procedure to define the node lines along the transverse (z) direction. Nodes are calculated based on
        number of longitudinal members and edge beam distance. Function is callable from outside class if user requires
        - does not affect the abstracted procedural call in the class.

        return: noz: list of nodes along line in the transverse direction.
        """
        # Function to output array of grid nodes along longitudinal direction
        last_girder = (self.width - self.edge_width)  # coord of last girder
        nox_girder = np.linspace(start=self.edge_width, stop=last_girder, num=self.num_long_gird-2)
        noz = np.hstack((np.hstack((0, nox_girder)), self.width))  # array containing z coordinate
        return noz

    # encapsulated meshing procedure for skew meshing
    def __skew_mesh(self):
        """
        Encapsulated meshing procedure for skew/oblique meshes.
        """
        # automate skew meshing
        self.nox = np.linspace(0, self.long_dim, self.num_trans_grid)  # array like containing node x coordinate
        self.breadth = self.trans_dim * math.sin(self.skew / 180 * math.pi)  # length of skew edge in x dir
        self.noz = self.get_long_grid_nodes()  # mesh points in z direction
        # identify member groups based on nox and noz
        self.__identify_member_groups()  # returns section_group_nox and section_group_noz
        # initiate tag counters for node and elements
        nodetagcounter = 1  # counter for nodetag
        eletagcounter = 1  # counter for eletag

        for zcount, pointz in enumerate(self.noz):  # loop for each mesh point in z dir
            noxupdate = self.nox - pointz * np.tan(
                self.skew / 180 * math.pi)  # get nox for current step in transverse mesh
            for xcount, pointx in enumerate(noxupdate):  # loop for each mesh point in x dir (nox)
                # populate nodedata array - inputs [nodetag,x,y,z, gridz tag, gridx tag]
                self.node_map.append(
                    [nodetagcounter, pointx, self.y_elevation, pointz, zcount,
                     xcount])  # NOTE here is where to change X Y plane
                nodetagcounter += 1
        # print to terminal
        print("Nodes created. Number of nodes = {}".format(nodetagcounter - 1))

        # procedure to link nodes to form Elements of grillage model
        # each element is then assigned a "standard element tag" e.g. self.longitudinal_tag = 1
        for node_row_z in range(0, len(self.noz)):  # loop for each line mesh in z direction
            for node_col_x in range(1, len(self.nox)):  # loop for each line mesh in x direction
                current_row_z = node_row_z * len(self.nox)  # get current row's (z axis) nodetagcounter
                next_row_z = (node_row_z + 1) * len(self.nox)  # get next row's (z axis) nodetagcounter
                # link nodes along current row (z axis), in the x direction
                # elements in a element list: [node_i, node_j, element group, ele tag, geomTransf (1,2 or 3), grid tag]
                self.long_mem.append([current_row_z + node_col_x, current_row_z + node_col_x + 1,
                                      self.section_group_noz[node_row_z], eletagcounter, 1, node_row_z])
                eletagcounter += 1

                # link nodes in the z direction (e.g. transverse members)
                if next_row_z == nodetagcounter - 1:  # if looping last row of line mesh z
                    pass  # do nothing (exceeded the z axis edge of the grillage)
                else:  # assigning elements in transverse direction (z)
                    self.trans_mem.append([current_row_z + node_col_x, next_row_z + node_col_x,
                                           self.section_group_nox[node_col_x - 1], eletagcounter, 2, node_col_x - 1])
                    # section_group_nox counts from 1 to 12, therefore -1 to start counter 0 to 11
                    eletagcounter += 1
            if next_row_z >= len(self.nox) * len(self.noz):  # check if current z coord is last row
                pass  # last column (x = self.nox[-1]) achieved, no more assignment
            else:  # assign last transverse member at last column (x = self.nox[-1])
                self.trans_mem.append([current_row_z + node_col_x + 1, next_row_z + node_col_x + 1,
                                       self.section_group_nox[node_col_x], eletagcounter, 2, node_col_x])
                # after counting section_group_nox 0 to 11, this line adds the counter of 12
                eletagcounter += 1
        # combine long and trans member elements to global list
        self.global_element_list = self.long_mem + self.trans_mem
        print("Element generation completed. Number of elements created = {}".format(eletagcounter - 1))
        # save elements and nodes to mesh object
        # mesh_group = Mesh(self.global_element_list, self.node_map)
        # return mesh_group

    # encapsulated meshing procedure for orthogonal meshing
    def __orthogonal_mesh(self):
        """
        Encapsulated meshing procedure for orthogonal meshes.
        """
        # Note special rule for nox does not apply to orthogonal mesh - automatically calculates the optimal ortho mesh
        #             o o o o o o
        #           o
        #         o
        #       o o o o o o
        #         b    +  ortho
        self.breadth = self.trans_dim * np.abs(math.sin(self.skew / 180 * math.pi))  # length of skew edge in x dir
        self.noz = self.get_long_grid_nodes()  # mesh points in transverse direction

        # Generate nox based on two orthogonal region: (A)  quadrilateral area, and (B)  triangular area
        self.regA = np.linspace(0, self.long_dim - self.breadth, self.num_trans_grid)
        # RegA consist of overlapping last element
        # RegB first element overlap with RegA last element
        self.regB = self.__get_region_b(self.regA[-1],
                                        self.noz)  # nodes @ region B startswith last entry of region A up to
        self.nox = np.hstack(
            (self.regA[:-1], self.regB))  # combined to form nox, with last node of regA removed for repeated val
        # identify member groups based on nox and noz
        self.__identify_member_groups()  # returns section_group_nox and section_group_noz
        # mesh region A quadrilateral area
        nodetagcounter = 1  # counter for nodetag, updates after creating each nodes
        eletagcounter = 1  # counter for element, updates after creating each elements
        for pointz in self.noz:  # loop for each mesh point in z dir
            for pointx in self.regA[:-1]:  # loop for each mesh point in x dir (nox)
                # populate nodedata array - inputs [nodetag,x,y,z]
                self.node_map.append([nodetagcounter, pointx, self.y_elevation, pointz])
                nodetagcounter += 1
        print('Number of elements in Region A: {}'.format(nodetagcounter - 1))

        # create elements of region A
        for node_row_z in range(0, len(self.noz)):
            for node_col_x in range(1, len(self.regA[:-1])):
                current_row_z = node_row_z * len(self.regA[:-1])  # current row's start node tag
                next_row_z = (node_row_z + 1) * len(  # next row's start node tag
                    self.regA[:-1])  # increment nodes after next self.noz (node grid along transverse)
                # link nodes along current row z
                self.long_mem.append([current_row_z + node_col_x, current_row_z + node_col_x + 1,
                                      self.section_group_noz[node_row_z], eletagcounter, 1])
                eletagcounter += 1

                # link nodes along current row in x dir (transverse)
                if next_row_z == nodetagcounter - 1:  # check if current z coord is last row
                    pass  # last column (x = self.nox[-1]) achieved, no more assigning transverse member

                else:
                    self.trans_mem.append([current_row_z + node_col_x, next_row_z + node_col_x,
                                           self.section_group_nox[node_col_x - 1], eletagcounter, 3])
                    eletagcounter += 1
                # last
            if next_row_z >= len(self.noz) * len(self.regA[:-1]):
                pass
            else:
                self.trans_mem.append([current_row_z + node_col_x + 1, next_row_z + node_col_x + 1,
                                       self.section_group_nox[node_col_x], eletagcounter, 3])
                # e.g. after counting section_group_nox 0 to 10, this line adds the counter of 11
                eletagcounter += 1
        print('Elements automation complete for region A: Number of elements = {}'.format(eletagcounter - 1))

        # node generation for region B
        # node generate B1 @ right support
        b1_node_tag_start = nodetagcounter - 1  # last node tag of region A
        regBupdate = self.regB  # initiate list for line mesh of region B1 - updated each loop by removing last element
        # record the section gruop counter
        reg_section_counter = node_col_x
        if self.skew < 0:  # check for angle sign
            line_mesh_z_b1 = reversed(self.noz)  # (0 to ascending for positive angle,descending for -ve)
        else:
            line_mesh_z_b1 = self.noz
        for pointz in line_mesh_z_b1:  # loop for each line mesh in z dir
            for pointx in regBupdate:  # loop for each line mesh in x dir (nox)
                self.node_map.append([nodetagcounter, pointx, self.y_elevation, pointz])
                nodetagcounter += 1
            regBupdate = regBupdate[:-1]  # remove last element for next self.noz (skew boundary)

        # Elements mesh for region B1
        regBupdate = self.regB  # reset placeholder
        row_start = b1_node_tag_start  # last nodetag of region A
        if self.skew < 0:
            reg_a_col = row_start  # nodetag of last node in last row of region A (last nodetag of region A)
        else:  # nodetag of last node in first row of region A
            reg_a_col = len(
                self.regA[:-1])  # the last node of a single row + ignore last element of reg A (overlap regB)
        for num_z in range(0, len(self.noz)):
            # element that link nodes with those from region A
            if self.skew < 0:  # if negative skew, loop starts from the last row (@ row = width)
                self.long_mem.append([reg_a_col, row_start + 1,
                                      self.section_group_noz[(-1 - num_z)], eletagcounter, 1])
                eletagcounter += 1
            else:  # skew is positive,
                self.long_mem.append([reg_a_col, row_start + 1,
                                      self.section_group_noz[num_z], eletagcounter, 1])
                eletagcounter += 1

            # loop for each column node in x dir
            # create elements for each nodes in current row (z axis) in the x direction (list regBupdate)
            for num_x in range(1, len(regBupdate)):
                if self.skew < 0:
                    self.long_mem.append([row_start + num_x, row_start + num_x + 1,
                                          self.section_group_noz[(-1 - num_z)], eletagcounter, 1])
                    eletagcounter += 1
                else:
                    self.long_mem.append([row_start + num_x, row_start + num_x + 1,
                                          self.section_group_noz[num_z], eletagcounter, 1])
                    eletagcounter += 1

                # transverse member
                self.trans_mem.append([row_start + num_x, row_start + num_x + len(regBupdate),
                                       self.section_group_nox[num_x + reg_section_counter], eletagcounter, 3])
                eletagcounter += 1
            if num_z != len(self.noz) - 1:  # check if current row (z) is the last row of the iteration;
                # if yes,  last node of skew is single node, no element, break the loop for self.noz
                # if no, run line below, to assign the skew edges
                self.trans_mem.append([row_start + num_x + 1, row_start + num_x + len(regBupdate),
                                       self.section_group_nox[-1], eletagcounter, 2])
                eletagcounter += 1

            row_start = row_start + len(regBupdate)  # update next self.noz start node of region B
            regBupdate = regBupdate[:-1]  # remove last element for next self.noz (skew boundary)
            # check for skew angle varients of region B1 loop (positive or negative)
            if self.skew < 0:
                reg_a_col = reg_a_col - len(
                    self.regA[:-1])  # update row node number correspond with region A (decreasing)
            else:
                reg_a_col = reg_a_col + len(
                    self.regA[:-1])  # update row node number correspond with region A (increasing)
        print('Elements automation complete for region B1 and A')

        # B2 left support
        regBupdate = -self.regB + self.regA[-1]  # left side of quadrilateral area, regB can lie in negative x axis
        if self.skew < 0:  # check for angle sign
            line_mesh_z_b2 = self.noz  # (descending for positive angle,ascending for -ve)
        else:
            line_mesh_z_b2 = reversed(self.noz)
        for pointz in line_mesh_z_b2:
            for pointx in regBupdate[1:]:  # remove counting first element overlap with region A
                self.node_map.append([nodetagcounter, pointx, self.y_elevation, pointz])
                nodetagcounter += 1
            regBupdate = regBupdate[:-1]  # remove last element (skew boundary) for next self.noz

        # Element meshing for region B2
        # takes row_start from B1 auto meshing loop
        if self.skew < 0:
            reg_a_col = 1  # links to first node (region A)
        else:
            reg_a_col = 1 + (len(self.noz) - 1) * len(self.regA[:-1])  # links to first node last row of region A
        regBupdate = -self.regB + self.regA[-1]  # reset placeholder
        for num_z in range(0, len(self.noz)):
            # link nodes from region A
            if num_z == len(self.noz) - 1:  # for z = 6
                # at last row of z nodes, there exist only a single point node (typically node 1)
                # therefore, no connection of nodes to form element - end loop
                break  #
            if self.skew < 0:
                self.long_mem.append([row_start + 1, reg_a_col, self.section_group_noz[num_z], eletagcounter, 1])
                eletagcounter += 1
            else:
                self.long_mem.append([row_start + 1, reg_a_col, self.section_group_noz[(-1 - num_z)], eletagcounter, 1])
                eletagcounter += 1

            # loop for each column node in x dir
            for num_x in range(1, len(regBupdate[1:])):
                if self.skew < 0:  # negative angle
                    #
                    self.long_mem.append(
                        [row_start + num_x + 1, row_start + num_x, self.section_group_noz[num_z], eletagcounter, 1])
                    eletagcounter += 1
                else:  # positive angle
                    self.long_mem.append(
                        [row_start + num_x + 1, row_start + num_x, self.section_group_noz[(-1 - num_z)], eletagcounter,
                         1])
                    eletagcounter += 1

                # assign transverse member (orthogonal)
                self.trans_mem.append([row_start + num_x, row_start + num_x + len(regBupdate[1:]),
                                       self.section_group_nox[num_x + reg_section_counter + 1], eletagcounter, 3])
                eletagcounter += 1
                # section_group +1 due to not counting the first column (x = 0) , also by default, the size of
                # regB in B2 region is N - 1 of the size of regB in B1.
                # Therefore assignment starts from 1, not 0 (hence+1 )

            # code to assign the skew edge (edge_slab)
            if num_z == len(self.noz) - 1:  # for z = 6
                # at last row of z nodes, there exist only a single point node (typically node 1)
                # therefore, no connection of nodes to form element - end loop
                break  #
            elif num_z == len(self.noz) - 2:  # if at the second last step z = 5
                # at this step, connect last element to node of region A to form skew edge
                if self.skew < 0:  # if negative angle
                    self.trans_mem.append(
                        [reg_a_col + len(self.regA[:-1]), row_start + len(regBupdate[1:]),
                         self.section_group_nox[-1], eletagcounter, 2])  # ele of node 1 to last node skew
                    eletagcounter += 1
                else:  # else positive skew
                    self.trans_mem.append(
                        [1, row_start + len(regBupdate[1:]), self.section_group_nox[-1],
                         eletagcounter, 2])  # ele of node 1 to last node skew
                    eletagcounter += 1
            elif num_z != len(self.noz) - 1:  # check if its not the last step
                # assign trasnverse members of region B2
                self.trans_mem.append(
                    [row_start + num_x + 1, row_start + num_x + len(regBupdate[1:]), self.section_group_nox[-1]
                        , eletagcounter, 2])  # support skew
                eletagcounter += 1
            # steps in transverse mesh, assign nodes of skew nodes

            row_start = row_start + len(regBupdate[1:])  # update next self.noz start node
            regBupdate = regBupdate[:-1]  # remove last element for next self.noz (skew boundary)

            if self.skew < 0:
                reg_a_col = reg_a_col + len(self.regA[:-1])  # update next self.noz node correspond with region A
            else:
                reg_a_col = reg_a_col - len(self.regA[:-1])  # update next self.noz node correspond with region A
        print('Elements automation complete for region B1 B2 and A')
        self.global_element_list = self.long_mem + self.trans_mem
        # save elements and nodes to mesh object


    def set_material(self, material_obj):
        """
        Function to define a global material model. This function proceeds to write write the material() command to
        output file.

        :return: Function populates object variables: (1) mat_matrix, and (2) mat_type_op.
        """
        # set material to global material object
        self.global_mat_object = material_obj  # material matrix for

        # write uniaxialMaterial() command to output file
        self.__write_uniaxial_material(material=material_obj)

    def run_check(self):
        """
        Test output file

        """
        try:
            __import__(self.filename[:-3])  # run file
            print("File successfully imported and run")
        except:
            print("File executed with error exceptions")

    def add_load_case(self, name, *load_obj, analysis_type='Static'):
        """
        Functions to add loads or load cases
        :param name:
        :param load_obj:
        :param analysis_type:
        :return:
        """

        with open(self.filename, 'a') as file_handle:
            # if no load cases have been defined previously, create time series object for the first time
            if not bool(self.load_case_dict):
                time_series = "ops.timeSeries('Constant', 1)\n"
                file_handle.write(time_series)
                eval(time_series)
                load_case_counter = 0  # if dict empty, start counter at 1
            else:  # set load_case_counter variable as the latest
                load_case_counter = self.load_case_dict[list(self.load_case_dict)[-1]]
                wipe_command = "ops.wipeAnalysis()\n"
                file_handle.write(wipe_command)  # write wipeAnalysis for current load case
                eval(wipe_command)

            # set load case to load_case_dict
            load_case_tag = self.load_case_dict.setdefault(name, load_case_counter + 1)
            # write header
            file_handle.write("#===========================\n# create load case {}\n#==========================\n"
                              .format(name))
            # create pattern obj for load case
            pattern_command = "ops.pattern('Plain', {}, 1)\n".format(load_case_tag)
            file_handle.write(pattern_command)
            eval(pattern_command)
            # print to terminal
            print("Load Case {} created".format(name))
            # loop through each load object
            for loads in load_obj:
                if isinstance(loads, NodalLoad):
                    load_str = loads.get_nodal_load_str()
                    for lines in load_str:
                        file_handle.write(lines)
                    # print to terminal
                    print("Nodal load - {loadname} - added to load case: {loadcase}".format(loadname=loads.name,
                                                                                            loadcase=name))
                elif isinstance(loads, PointLoad):
                    nod = self.__return_four_node_position(position=loads.position)
                    print(nod)

                elif isinstance(loads, LineLoading):
                    load_str = self.__assign_line_load(line_position_x=2, udl_value=2)
                    for lines in load_str:
                        file_handle.write(lines)
                    print("Line load - {loadname} - added to load case: {name}".format(loadname=loads.name, name=name))

                elif isinstance(loads, PatchLoading):
                    if loads.patch_define_option == "two-lines":
                        load_str = self.__assign_patch_load_bound_option(bound_lines=loads.northing_lines,
                                                                         area_load=loads.qy)
                    elif loads.patch_define_option == "four-points":
                        # TODO
                        pass

                    for lines in load_str:
                        file_handle.write(lines)
                    print("Patch load - {loadname} - added to load case: {name}".format(loadname=loads.name, name=name))
                else:
                    print("No loads assigned for {}".format(loads))

            # Create instance and write command to output py file
            file_handle.write("ops.integrator('LoadControl', 1)\n")  # Header
            file_handle.write("ops.numberer('Plain')\n")
            file_handle.write("ops.system('BandGeneral')\n")
            file_handle.write("ops.constraints('Plain')\n")
            file_handle.write("ops.algorithm('Linear')\n")
            file_handle.write("ops.analysis(\"{}\")\n".format(analysis_type))
            file_handle.write("ops.analyze(1)\n")

    # ---------------------------------------------------------------
    # assignment procedure
    # TO be retired
    def __return_four_node_position(self, position):
        # function called by OpsGrillage to identify the position of point load/axle
        # position [x,z]
        # find grid lines that bound position in x direction
        grid_a_z, grid_b_z = search_grid_lines(self.noz, position=position[1])
        # return nodes in the bounded grid lines grid_a_z and grid_b_z
        grid_b_z_nodes = [x for x in self.node_map if x[4] == grid_a_z]
        grid_a_z_nodes = [x for x in self.node_map if x[4] == grid_b_z]
        # loop each grid nodes to find the two closest nodes in the x direction (vector distance)
        node_distance = []
        for node in grid_b_z_nodes:
            dis = np.sqrt((node[1] - position[0]) ** 2 + 0 + (node[3] - position[1]) ** 2)
            node_distance.append([node[0], dis])
        for node in grid_a_z_nodes:
            dis = np.sqrt((node[1] - position[0]) ** 2 + 0 + (node[3] - position[1]) ** 2)
            node_distance.append([node[0], dis])
        node_distance.sort(key=lambda x: x[1])
        n1 = node_distance[0]
        n2 = node_distance[1]
        n3 = node_distance[2]
        n4 = node_distance[3]
        return [x[0] for x in [n1, n2, n3, n4]]

    # TO be retired
    def __assign_line_load(self, line_position_x, udl_value):
        line = search_grid_lines(self.noz, position=line_position_x)
        load_str = []
        # TODO allow assignment for transverse members
        for ele in self.long_mem:
            if ele[5] == line[1][0]:
                eleLoad_line = "ops.eleLoad('-ele', {eleTag}, '-type', '-beamUniform', {Wy}, {Wz}, {Wx})\n" \
                    .format(eleTag=ele[3], Wy=0, Wx=0, Wz=0)
            elif ele[5] == line[0][0]:
                eleLoad_line = "ops.eleLoad('-ele', {eleTag}, '-type', '-beamUniform', {Wy}, {Wz}, {Wx})\n" \
                    .format(eleTag=ele[3], Wy=0, Wx=0, Wz=0)
            else:
                eleLoad_line = ''
            load_str.append(eleLoad_line)
        return load_str

    # TO be retired
    def __assign_patch_load_bound_option(self, bound_lines, area_load):
        if bound_lines[0] > bound_lines[1]:
            ub_nd_line = search_grid_lines(self.noz, position=bound_lines[0], position_bound="ub")
            lb_nd_line = search_grid_lines(self.noz, position=bound_lines[1], position_bound="lb")
        else:
            lb_nd_line = search_grid_lines(self.noz, position=bound_lines[0], position_bound="lb")
            ub_nd_line = search_grid_lines(self.noz, position=bound_lines[1], position_bound="ub")
        load_str = []
        # if lower bound = upper bound, no in between lines, only assign to the single line identified by
        # lower_bound_nd_line/upper_bound_nd_line
        # if ub_nd_line and lb_nd_line are identical, patch load area too small for definition of patch load
        if lb_nd_line[0][0] == ub_nd_line[0][0] and lb_nd_line[1][0] == ub_nd_line[1][0]:
            # print warning to Terminal
            print('Northing bounds too small for definition of patch loads - consider line load instead ')

        # if bounded line is common, set load to
        elif lb_nd_line[0] == ub_nd_line[1]:
            in_between_nd_line = [lb_nd_line[0][0]]
            lb_nd_line[0] = [[], 0]
            ub_nd_line[1] = [[], 0]
        elif lb_nd_line[0][0] + 1 == ub_nd_line[1][0]:
            in_between_nd_line = []
        else:
            in_between_nd_line = [lb_nd_line[0][0] + 1]
            while not in_between_nd_line[-1] + 1 > ub_nd_line[1][0]:
                in_between_nd_line.append(in_between_nd_line[-1] + 1)

        # loop all between node lines, assign udl using full width of node tributary area
        for nd_line in in_between_nd_line:
            nd_wid = self.noz_trib_width[nd_line]
            udl_line = area_load * nd_wid
            for ele in self.long_mem:
                # if element is part of the grid line, assign UDl using eleLoad command
                if ele[5] == nd_line:
                    eleLoad_line = "ops.eleLoad('-ele', {eleTag}, '-type', '-beamUniform', {Wy}, {Wz}, {Wx})\n" \
                        .format(eleTag=ele[3], Wy=udl_line, Wx=0, Wz=0)
                    load_str.append(eleLoad_line)
        # assign ub and lb udl
        for ele in self.long_mem:
            if ele[5] == lb_nd_line[1][0]:
                eleLoad_line = "ops.eleLoad('-ele', {eleTag}, '-type', '-beamUniform', {Wy}, {Wz}, {Wx})\n" \
                    .format(eleTag=ele[3], Wy=area_load * lb_nd_line[1][1], Wx=0, Wz=0)
            elif ele[5] == lb_nd_line[0][0]:
                eleLoad_line = "ops.eleLoad('-ele', {eleTag}, '-type', '-beamUniform', {Wy}, {Wz}, {Wx})\n" \
                    .format(eleTag=ele[3], Wy=area_load * lb_nd_line[0][1], Wx=0, Wz=0)
            elif ele[5] == ub_nd_line[1][0]:
                eleLoad_line = "ops.eleLoad('-ele', {eleTag}, '-type', '-beamUniform', {Wy}, {Wz}, {Wx})\n" \
                    .format(eleTag=ele[3], Wy=area_load * ub_nd_line[1][1], Wx=0, Wz=0)
            elif ele[5] == ub_nd_line[0][0]:
                eleLoad_line = "ops.eleLoad('-ele', {eleTag}, '-type', '-beamUniform', {Wy}, {Wz}, {Wx})\n" \
                    .format(eleTag=ele[3], Wy=area_load * ub_nd_line[0][1], Wx=0, Wz=0)
            else:
                eleLoad_line = ""
            load_str.append(eleLoad_line)
        # TODO filter longitudinal members for easting lines

        return load_str
